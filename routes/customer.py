from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import selectinload
from models import db, Customer
from flask_babel import _
import json
import io
from cryptography.fernet import InvalidToken
from services.core import CustomerService
from .utils import require_permission

customer_bp = Blueprint('customer', __name__)

@customer_bp.route('/')
@login_required
@require_permission('view_customer')
def customers_list():
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    # Enforce multi-tenancy: users only see customers from their location
    # Optimization: Eager load devices to prevent N+1 queries when rendering the device count column
    stmt = select(Customer).options(selectinload(Customer.devices)).where(Customer.location_id == current_user.location_id)
    
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
        selectinload(Customer.tickets)
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
        success, result = CustomerService.create_customer(
            request.form.get('name'), 
            request.form.get('phone'), 
            request.form.get('address', ''),
            location_id=current_user.location_id # Link to current location
        )
        if success:
            db.session.commit()
            flash(_('Customer created successfully!'), 'success')
            return redirect(url_for('customer.customers_list'))
        flash(result, 'error')
    return render_template('customers/new_customer.html')

@customer_bp.route('/search', methods=['GET'])
@login_required
@require_permission('view_customer')
def search_customers():
    query = request.args.get('q', '').strip()
    if len(query) < 2: return jsonify([])
    query_hash = Customer.get_search_hash(query)
    # Scope search to current location
    stmt = db.select(Customer).filter_by(location_id=current_user.location_id).filter(
        or_(Customer.name.ilike(f'%{query}%'), Customer.phone_hash == query_hash)
    ).limit(10)
    customers = db.session.execute(stmt).scalars().all()
    return jsonify([{'id': c.id, 'name': c.name, 'phone': c.phone} for c in customers])

@customer_bp.route('/export/<int:customer_id>')
@login_required
@require_permission('view_customer')
def export_customer_data(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer or (not current_user.is_superuser and customer.location_id != current_user.location_id): return redirect(url_for('customer.customers_list'))
    data = customer.export_data()
    output = io.BytesIO(json.dumps(data, indent=4).encode('utf-8'))
    return send_file(output, mimetype='application/json', as_attachment=True, download_name=f"customer_{customer_id}.json")

@customer_bp.route('/anonymize/<int:customer_id>', methods=['POST'])
@login_required
@require_permission('delete_customer')
def anonymize_customer(customer_id):
    customer = db.session.get(Customer, customer_id)
    if customer and (current_user.is_superuser or customer.location_id == current_user.location_id):
        customer.anonymize()
        db.session.commit()
        flash(_('Customer data anonymized.'), 'success')
    return redirect(url_for('customer.customers_list'))

@customer_bp.route('/new', methods=['POST'])
@login_required
@require_permission('create_customer')
def new_customer_ajax():
    success, result = CustomerService.create_customer(
        request.form.get('name'), 
        request.form.get('phone'), 
        request.form.get('address', ''),
        location_id=current_user.location_id
    )
    if success:
        db.session.commit()
        return jsonify({'id': result.id, 'name': result.name})
    return jsonify({'error': result}), 500