from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import selectinload, joinedload
from models import db, Customer, Location, Ticket
from flask_babel import _
import json
import io
from services.core import CustomerService
from .utils import require_permission

customer_bp = Blueprint('customer', __name__)

@customer_bp.route('/')
@login_required
@require_permission('view_customer')
def customers_list():
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    
    # SCALABILITY: Enforce multi-tenancy with superuser visibility override
    location_filter = Customer.location_id == current_user.location_id if not current_user.is_superuser else True
    
    # Optimization: Eager load devices to prevent N+1 queries when rendering the device count column
    stmt = select(Customer).options(selectinload(Customer.devices)).where(location_filter)
    
    if search_query:
        query_hash = Customer.get_search_hash(search_query)
        stmt = stmt.filter(or_(Customer.name.ilike(f'%{search_query}%'), Customer.phone_hash == query_hash))
    customers = db.paginate(stmt.order_by(desc(Customer.created_at)), page=page, per_page=15)
    return render_template('customers/customers.html', customers=customers, search_query=search_query)

@customer_bp.route('/view/<int:customer_id>', endpoint='view_customer')
@login_required
@require_permission('view_customer')
def view_customer(customer_id):
    # Optimization: Eager load devices and tickets for the 360-degree view
    stmt = select(Customer).options(
        selectinload(Customer.devices),
        selectinload(Customer.tickets).joinedload(Ticket.device)
    ).where(Customer.id == customer_id)
    
    customer = db.session.scalar(stmt)

    if not customer or (not current_user.is_superuser and customer.location_id != current_user.location_id):
        flash(_('Customer not found'), 'error')
        return redirect(url_for('customer.customers_list'))
    return render_template('customers/customer_detail.html', customer=customer)

@customer_bp.route('/new_customer', methods=['GET', 'POST'])
@login_required
@require_permission('create_customer')
def new_customer():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        
        if not name or not phone:
            flash(_('Name and phone are required.'), 'error')
        else:
            # INTEGRITY: Ensure a location is associated even if created by a global superuser
            loc_id = current_user.location_id or db.session.scalar(select(Location.id).limit(1))

            success, result = CustomerService.create_customer(
                name, phone, address,
                location_id=loc_id
            )
            if success:
                try:
                    db.session.commit()
                    flash(_('Customer created successfully!'), 'success')
                    return redirect(url_for('customer.customers_list'))
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Customer creation database error: {str(e)}")
                    flash(_('A database error occurred while creating the customer.'), 'error')
            else:
                flash(result, 'error')
            
        # UX: Return form data to template to prevent data loss on validation error
        return render_template('customers/new_customer.html', name=name, phone=phone, address=address)
    return render_template('customers/new_customer.html')

@customer_bp.route('/search', methods=['GET'])
@login_required
@require_permission('view_customer')
def search_customers():
    query = request.args.get('q', '').strip()
    if len(query) < 2: return jsonify([])
    query_hash = Customer.get_search_hash(query)
    
    # SCALABILITY: Scope search to current location or all if superuser
    location_filter = Customer.location_id == current_user.location_id if not current_user.is_superuser else True
    stmt = db.select(Customer).where(location_filter).filter(
        or_(Customer.name.ilike(f'%{query}%'), Customer.phone_hash == query_hash)
    ).limit(10)
    customers = db.session.execute(stmt).scalars().all()
    return jsonify([{'id': c.id, 'name': c.name, 'phone': c.phone} for c in customers])

@customer_bp.route('/export/<int:customer_id>')
@login_required
@require_permission('view_customer')
def export_customer_data(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer or (not current_user.is_superuser and customer.location_id != current_user.location_id):
        flash(_('Access denied or customer not found.'), 'error')
        return redirect(url_for('customer.customers_list'))
        
    data = customer.export_data()
    output = io.BytesIO(json.dumps(data, indent=4).encode('utf-8'))
    return send_file(output, mimetype='application/json', as_attachment=True, download_name=f"customer_{customer_id}.json")

@customer_bp.route('/anonymize/<int:customer_id>', methods=['POST'])
@login_required
@require_permission('delete_customer')
def anonymize_customer(customer_id):
    customer = db.session.get(Customer, customer_id)
    if customer and (current_user.is_superuser or customer.location_id == current_user.location_id):
        try:
            customer.anonymize()
            db.session.commit()
            flash(_('Customer data anonymized.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Customer anonymization error: {str(e)}")
            flash(_('A database error occurred during anonymization.'), 'error')
    return redirect(url_for('customer.customers_list'))

@customer_bp.route('/new', methods=['POST'])
@login_required
@require_permission('create_customer')
def new_customer_ajax():
    name = request.form.get('name', '').strip()
    phone = request.form.get('phone', '').strip()
    address = request.form.get('address', '').strip()

    if not name or not phone:
        return jsonify({'error': _('Name and phone are required.')}), 400

    # INTEGRITY: Identify appropriate location for the new record
    loc_id = current_user.location_id or db.session.scalar(select(Location.id).limit(1))
    success, result = CustomerService.create_customer(
        name, phone, address,
        location_id=loc_id
    )
    if success:
        try:
            db.session.commit()
            return jsonify({'id': result.id, 'name': result.name})
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Customer AJAX creation database error: {str(e)}")
            return jsonify({'error': _('A database error occurred while creating the customer.')}), 500
    return jsonify({'error': result}), 400 # Use 400 for client-side validation errors