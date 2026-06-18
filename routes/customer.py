import io
import json

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy import desc, or_
from sqlalchemy.orm import selectinload

from models import Customer, Location, Ticket, db
from services.core import CustomerService
from .utils import require_permission

customer_bp = Blueprint('customer', __name__)

@customer_bp.route('/')
@login_required
@require_permission('view_customer')
def customers_list():
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    selected_location = request.args.get('location_id', type=int)
    show_deleted = request.args.get('show_deleted', 0, type=int)
    
    # Multi-tenancy: Staff see their branch, superusers can filter or see all
    locations = []
    if current_user.is_superuser:
        # Fetch all locations for the filter dropdown
        locations = db.session.scalars(db.select(Location).order_by(Location.name)).all()
        location_filter = Customer.location_id == selected_location if selected_location else True
    else:
        location_filter = Customer.location_id == current_user.location_id
    
    # Optimization: Eager load devices to prevent N+1 queries when rendering the device count column
    stmt = db.select(Customer).options(selectinload(Customer.devices)).where(location_filter)
    
    # Integrity: By default, filter out anonymized (deleted) users unless explicitly requested
    if show_deleted != 1:
        # Robustness: Filter by flag and also handle legacy scrubbed records (GDPR integrity)
        stmt = stmt.where(
            (Customer.is_anonymized.is_(False)) & (~Customer.name.ilike('DELETED_USER_%'))
        )

    if search_query:
        query_hash = Customer.get_search_hash(search_query)
        # INTEGRITY: Only compare against phone_hash if the query contains numeric digits
        search_filters = [Customer.name.ilike(f'%{search_query}%')]
        if query_hash:
            search_filters.append(Customer.phone_hash == query_hash)
        stmt = stmt.where(or_(*search_filters))
    customers = db.paginate(stmt.order_by(desc(Customer.created_at)), page=page, per_page=15)
    return render_template('customers/customers.html', customers=customers, search_query=search_query, locations=locations, selected_location=selected_location, show_deleted=show_deleted)

@customer_bp.route('/view/<int:customer_id>')
@login_required
@require_permission('view_customer')
def view_customer(customer_id):
    # Optimization: Eager load devices and tickets for the 360-degree view
    stmt = db.select(Customer).options(
        selectinload(Customer.devices),
        selectinload(Customer.tickets).joinedload(Ticket.device)
    ).where(Customer.id == customer_id)
    
    customer = db.session.scalar(stmt)

    if not customer or (not current_user.is_superuser and customer.location_id != current_user.location_id):
        flash(_('Customer not found'), 'danger')
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
            flash(_('Name and phone are required.'), 'danger')
        else:
            # INTEGRITY: Ensure a location is associated even if created by a global superuser
            loc_id = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))

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
                    flash(_('A database error occurred while creating the customer.'), 'danger')
            else:
                flash(result, 'danger')
            
        # UX: Return form data to template to prevent data loss on validation error
        return render_template('customers/new_customer.html', name=name, phone=phone, address=address)
    return render_template('customers/new_customer.html')

@customer_bp.route('/edit/<int:customer_id>', methods=['GET', 'POST'])
@login_required
@require_permission('edit_customer')
def edit_customer(customer_id):
    """Allows updating existing customer contact information"""
    customer = db.session.get(Customer, customer_id)
    
    if not customer or (not current_user.is_superuser and customer.location_id != current_user.location_id):
        flash(_('Customer not found'), 'danger')
        return redirect(url_for('customer.customers_list'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        
        if not name or not phone:
            flash(_('Name and phone are required.'), 'danger')
        else:
            # INTEGRITY: Check for duplicate phone number at this location before updating
            # This prevents record fragmentation and maintains CRM accuracy.
            new_hash = Customer.get_search_hash(phone)
            exists = db.session.scalar(db.select(Customer.id).where(
                Customer.phone_hash == new_hash,
                Customer.location_id == customer.location_id,
                Customer.id != customer_id
            ))
            if exists:
                flash(_('A customer with this phone number already exists at this location.'), 'danger')
                # UX FIX: Return attempted values to prevent data loss on validation error
                return render_template('customers/edit_customer.html', customer=customer,
                                       name=name, phone=phone, address=address)

            customer.name = name
            customer.phone = phone
            customer.address = address
            try:
                db.session.commit()
                flash(_('Customer updated successfully!'), 'success')
                return redirect(url_for('customer.view_customer', customer_id=customer.id))
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Customer update database error: {str(e)}")
                flash(_('A database error occurred while updating the customer.'), 'danger')
        
        # UX FIX: Return attempted values to prevent data loss on validation error
        return render_template('customers/edit_customer.html', customer=customer, name=name, phone=phone, address=address)
        
    return render_template('customers/edit_customer.html', customer=customer)

@customer_bp.route('/search', methods=['GET'])
@login_required
@require_permission('view_customer')
def search_customers():
    query = request.args.get('q', '').strip()
    if len(query) < 2: return jsonify([])
    query_hash = Customer.get_search_hash(query)

    # Privacy: Hide anonymized users from global AJAX search results by default
    active_filter = (Customer.is_anonymized.is_(False)) & (~Customer.name.ilike('DELETED_USER_%'))

    # SCALABILITY: Scope search to current location or all if superuser
    location_filter = Customer.location_id == current_user.location_id if not current_user.is_superuser else (Customer.location_id == request.args.get('location_id', type=int) if request.args.get('location_id') else True)
    stmt = db.select(Customer).where(location_filter).where(active_filter)

    # INTEGRITY: Ensure the search logic handles text-only queries safely
    search_filters = [Customer.name.ilike(f'%{query}%')]
    if query_hash:
        search_filters.append(Customer.phone_hash == query_hash)
        
    stmt = stmt.where(or_(*search_filters)).limit(10)

    customers = db.session.scalars(stmt).all()
    return jsonify([{'id': c.id, 'name': c.name, 'phone': c.phone} for c in customers])

@customer_bp.route('/export/<int:customer_id>')
@login_required
@require_permission('export_customer')
def export_customer_data(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer or (not current_user.is_superuser and customer.location_id != current_user.location_id):
        flash(_('Access denied or customer not found.'), 'danger')
        return redirect(url_for('customer.customers_list'))
        
    data = customer.export_data()
    current_app.logger.info(f"PII Export: User {current_user.username} exported data for customer ID {customer_id}")
    output = io.BytesIO(json.dumps(data, indent=4, ensure_ascii=False).encode('utf-8'))
    return send_file(output, mimetype='application/json', as_attachment=True, download_name=f"customer_{customer_id}.json")

@customer_bp.route('/anonymize/<int:customer_id>', methods=['POST'])
@login_required
@require_permission('delete_customer')
def anonymize_customer(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer or (not current_user.is_superuser and customer.location_id != current_user.location_id):
        flash(_('Access denied or customer not found.'), 'danger')
        return redirect(url_for('customer.customers_list'))
        
    try:
        customer.anonymize()
        db.session.commit()
        current_app.logger.info(f"PII Anonymization: User {current_user.username} anonymized customer ID {customer_id}")
        flash(_('Customer data anonymized.'), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Customer anonymization error: {str(e)}")
        flash(_('A database error occurred during anonymization.'), 'danger')

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
    loc_id = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
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