from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import joinedload, selectinload
from models import db, Customer, Device
from flask_babel import _
from services.core import DeviceService
from .utils import require_permission

device_bp = Blueprint('device', __name__)

@device_bp.route('/')
@login_required
def devices_list():
    page = request.args.get('page', 1, type=int)
    # Filter by customer location
    stmt = db.select(Device).options(
        joinedload(Device.customer),
        selectinload(Device.tickets)
    ).join(Customer).filter(
        Customer.location_id == current_user.location_id
    ).order_by(desc(Device.created_at))
    
    devices = db.paginate(stmt, page=page, per_page=15)
    return render_template('devices/devices.html', devices=devices)

@device_bp.route('/view/<int:device_id>')
@login_required
def view_device(device_id):
    # Optimization: Eager load the owner and the full repair history 
    # to prevent N+1 queries in the detail template.
    stmt = select(Device).options(
        joinedload(Device.customer),
        selectinload(Device.tickets)
    ).where(Device.id == device_id)
    device = db.session.scalar(stmt)

    if not device:
        flash(_('Device not found'), 'error')
        return redirect(url_for('device.devices_list'))
        
    if not current_user.is_superuser and device.customer.location_id != current_user.location_id:
        flash(_('Access denied.'), 'error')
        return redirect(url_for('device.devices_list'))
        
    return render_template('devices/device_detail.html', device=device)

@device_bp.route('/new_device', methods=['GET', 'POST'])
@login_required
@require_permission('create_device')
def new_device():
    if request.method == 'POST':
        customer_id = request.form.get('customer_id', type=int)
        
        # Scoping check: Ensure the customer belongs to this location
        customer = db.session.get(Customer, customer_id)
        if not customer or (not current_user.is_superuser and customer.location_id != current_user.location_id):
            flash(_('Invalid customer selection.'), 'error')
            return redirect(url_for('device.new_device'))

        success, result = DeviceService.create_device(
            customer_id=customer_id,
            device_type=request.form.get('device_type'),
            brand=request.form.get('brand'),
            model_number=request.form.get('model_number'),
            serial_number=request.form.get('serial_number', '').strip().upper() or None,
            color=request.form.get('color'),
            cpu=request.form.get('cpu'),
            ram=request.form.get('ram'),
            storage_type=request.form.get('storage_type'),
            storage_capacity=request.form.get('storage_capacity'),
            notes=request.form.get('notes')
        )
        if success:
            db.session.commit()
            flash(_('Device added successfully!'), 'success')
            return redirect(url_for('device.devices_list'))
        flash(result, 'error')
    # Unified SQLAlchemy 2.0 query for customer selection
    cust_stmt = db.select(Customer).filter_by(location_id=current_user.location_id).order_by(Customer.name)
    customers = db.session.execute(cust_stmt).scalars().all()
    return render_template('devices/new_device.html', customers=customers)

@device_bp.route('/edit/<int:device_id>', methods=['GET', 'POST'])
@login_required
@require_permission('edit_device')
def edit_device(device_id):
    device = db.session.get(Device, device_id)
    if not device: return redirect(url_for('device.devices_list'))
    # Scoping check
    if not current_user.is_superuser and device.customer.location_id != current_user.location_id:
        flash(_('Access denied.'), 'error')
        return redirect(url_for('device.devices_list'))
        
    if request.method == 'POST':
        brand = request.form.get('brand')
        device_type = request.form.get('device_type')
        
        if not brand or not device_type:
            flash(_('Device type and brand are required.'), 'error')
            return render_template('devices/edit_device.html', device=device)

        device.device_type = device_type
        device.brand = brand
        device.model_number = request.form.get('model_number')
        # Integrity: Standardize serial numbers for better searchability
        device.serial_number = request.form.get('serial_number', '').strip().upper() or None
        device.cpu = request.form.get('cpu')
        device.ram = request.form.get('ram')
        device.storage_type = request.form.get('storage_type')
        device.storage_capacity = request.form.get('storage_capacity')
        device.color = request.form.get('color')
        device.notes = request.form.get('notes')
        
        db.session.commit()
        flash(_('Device updated.'), 'success')
        return redirect(url_for('device.view_device', device_id=device.id))
    return render_template('devices/edit_device.html', device=device)

@device_bp.route('/delete/<int:device_id>', methods=['POST'])
@login_required
@require_permission('delete_device')
def delete_device(device_id):
    device = db.session.get(Device, device_id)
    if device and (current_user.is_superuser or device.customer.location_id == current_user.location_id):
        cid = device.customer_id
        db.session.delete(device)
        db.session.commit()
        return redirect(url_for('customer.view_customer', customer_id=cid))
    return redirect(url_for('device.devices_list'))

@device_bp.route('/search/<int:customer_id>', methods=['GET'])
@login_required
def search_devices(customer_id):
    query = request.args.get('q', '').strip()
    # Integrity check: Ensure device search is within current location
    device_stmt = db.select(Device).join(Customer).where(
        Customer.id == customer_id, 
        Customer.location_id == current_user.location_id
    )
    if query:
        device_stmt = device_stmt.where(or_(Device.brand.ilike(f'%{query}%'), Device.model_number.ilike(f'%{query}%')))
    devices = db.session.execute(device_stmt.limit(10)).scalars().all()
    return jsonify([{'id': d.id, 'display': d.display} for d in devices])

@device_bp.route('/new', methods=['POST'])
@login_required
@require_permission('create_device')
def new_device_ajax():
    customer_id = request.form.get('customer_id', type=int)
    customer = db.session.get(Customer, customer_id)
    
    if not customer or (not current_user.is_superuser and customer.location_id != current_user.location_id):
        return jsonify({'error': _('Invalid customer.')}), 403

    success, result = DeviceService.create_device(
        customer_id=customer_id,
        device_type=request.form.get('device_type'),
        brand=request.form.get('brand'),
        model_number=request.form.get('model_number'),
        serial_number=request.form.get('serial_number', '').strip().upper() or None,
        cpu=request.form.get('cpu'),
        ram=request.form.get('ram'),
        storage_type=request.form.get('storage_type'),
        storage_capacity=request.form.get('storage_capacity'),
        color=request.form.get('color')
    )
    if success:
        db.session.commit()
        return jsonify({'id': result.id, 'display': result.display})
    return jsonify({'error': result}), 500