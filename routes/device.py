from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import joinedload, selectinload

from models import Customer, Device, Location, Ticket, db
from services.core import DeviceService
from .utils import require_permission

device_bp = Blueprint('device', __name__)

@device_bp.route('/')
@login_required
@require_permission('view_device')
def devices_list():
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('q', '').strip()
    selected_location = request.args.get('location_id', type=int)
    
    # Multi-tenancy: Staff see their branch, superusers can filter or see all
    locations = []
    if current_user.is_superuser:
        # Fetch all locations for the filter dropdown
        locations = db.session.scalars(db.select(Location).order_by(Location.name)).all()
        location_filter = Customer.location_id == selected_location if selected_location else True
    else:
        location_filter = Customer.location_id == current_user.location_id

    stmt = db.select(Device).options(
        joinedload(Device.customer),
        selectinload(Device.tickets)
    ).join(Customer).where(location_filter)

    if search_query:
        stmt = stmt.where(
            or_(
                Device.brand.ilike(f'%{search_query}%'),
                Device.model_number.ilike(f'%{search_query}%'),
                Device.serial_number.ilike(f'%{search_query}%'),
                Customer.name.ilike(f'%{search_query}%'),
                Customer.phone_hash == Customer.get_search_hash(search_query)
            )
        )
    
    stmt = stmt.order_by(desc(Device.created_at))
    
    devices = db.paginate(stmt, page=page, per_page=15) # type: ignore
    return render_template('devices/devices.html', devices=devices, search_query=search_query, locations=locations, selected_location=selected_location)

@device_bp.route('/view/<int:device_id>')
@login_required
@require_permission('view_device')
def view_device(device_id):
    # Optimization: Eager load the owner and the full repair history 
    # to prevent N+1 queries in the detail template.
    stmt = db.select(Device).options(
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
    # Unified SQLAlchemy 2.0 query for customer selection with multi-tenancy override
    location_filter = Customer.location_id == current_user.location_id if not current_user.is_superuser else True
    cust_stmt = db.select(Customer).where(location_filter).order_by(Customer.name)
    customers = db.session.scalars(cust_stmt).all()

    if request.method == 'POST':
        customer_id = request.form.get('customer_id', type=int)
        raw_serial = request.form.get('serial_number', '').strip().upper()
        serial_number = raw_serial or None
        
        # Scoping check: Ensure the customer belongs to this location
        customer = db.session.get(Customer, customer_id)
        if not customer or (not current_user.is_superuser and customer.location_id != current_user.location_id):
            flash(_('Invalid customer selection.'), 'error')
        else:
            success, result = DeviceService.create_device(
                customer_id=customer_id,
                device_type=request.form.get('device_type'),
                brand=request.form.get('brand'),
                model_number=request.form.get('model_number'),
                serial_number=serial_number,
                color=request.form.get('color'),
                cpu=request.form.get('cpu'),
                ram=request.form.get('ram'),
                storage_type=request.form.get('storage_type'),
                storage_capacity=request.form.get('storage_capacity'),
                notes=request.form.get('notes')
            )
            if success:
                try:
                    db.session.commit()
                    flash(_('Device added successfully!'), 'success')
                    return redirect(url_for('device.devices_list'))
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Device creation database error: {str(e)}")
                    flash(_('A database error occurred while saving the device.'), 'error')
            else:
                flash(result, 'error')
        
        # UX: Return form data to prevent data loss on validation error
        return render_template('devices/new_device.html', 
                               customers=customers,
                               customer_id=customer_id,
                               device_type=request.form.get('device_type'),
                               brand=request.form.get('brand'),
                               model_number=request.form.get('model_number'),
                               serial_number=raw_serial,
                               color=request.form.get('color'),
                               cpu=request.form.get('cpu'),
                               ram=request.form.get('ram'),
                               storage_type=request.form.get('storage_type'),
                               storage_capacity=request.form.get('storage_capacity'),
                               notes=request.form.get('notes'))
    return render_template('devices/new_device.html', customers=customers)

@device_bp.route('/edit/<int:device_id>', methods=['GET', 'POST'])
@login_required
@require_permission('edit_device')
def edit_device(device_id):
    device = db.session.get(Device, device_id)
    if not device:
        flash(_('Device not found'), 'error')
        return redirect(url_for('device.devices_list'))

    # Scoping check
    if not current_user.is_superuser and device.customer.location_id != current_user.location_id:
        flash(_('Access denied.'), 'error')
        return redirect(url_for('device.devices_list'))
        
    if request.method == 'POST':
        # UX Integrity: Update object with form data to preserve input on validation failure
        device.brand = request.form.get('brand')
        device.device_type = request.form.get('device_type')
        device.model_number = request.form.get('model_number')
        device.serial_number = request.form.get('serial_number', '').strip().upper() or None
        device.cpu = request.form.get('cpu')
        device.ram = request.form.get('ram')
        device.storage_type = request.form.get('storage_type')
        device.storage_capacity = request.form.get('storage_capacity')
        device.color = request.form.get('color')
        device.notes = request.form.get('notes')
        
        if not device.brand or not device.device_type:
            flash(_('Device type and brand are required.'), 'error')
            return render_template('devices/edit_device.html', device=device)
            
        try:
            db.session.commit()
            flash(_('Device updated.'), 'success')
            return redirect(url_for('device.view_device', device_id=device.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Device update database error: {str(e)}")
            flash(_('An error occurred while updating the device.'), 'error')
    return render_template('devices/edit_device.html', device=device)

@device_bp.route('/delete/<int:device_id>', methods=['POST'])
@login_required
@require_permission('delete_device')
def delete_device(device_id):
    device = db.session.get(Device, device_id)
    if not device:
        flash(_('Device not found'), 'error')
        return redirect(url_for('device.devices_list'))

    if not current_user.is_superuser and device.customer.location_id != current_user.location_id:
        flash(_('Access denied.'), 'error')
        return redirect(url_for('device.devices_list'))

    # INTEGRITY: Check for linked tickets before deletion
    linked_tickets = db.session.scalar(db.select(func.count(Ticket.id)).where(Ticket.device_id == device_id)) or 0
    if linked_tickets > 0:
        flash(_('Cannot delete device: It is linked to %(count)s tickets. Archive it instead.', count=linked_tickets), 'error')
        return redirect(url_for('device.view_device', device_id=device_id))

    try:
        cid = device.customer_id
        db.session.delete(device)
        db.session.commit()
        flash(_('Device deleted successfully.'), 'success')
        return redirect(url_for('customer.view_customer', customer_id=cid))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Device deletion database error: {str(e)}")
        flash(_('An error occurred while deleting the device.'), 'error')
        return redirect(url_for('device.view_device', device_id=device_id))

@device_bp.route('/search/<int:customer_id>', methods=['GET'])
@login_required
@require_permission('view_device')
def search_devices(customer_id):
    query = request.args.get('q', '').strip()
    
    # Integrity check: Ensure device search respects multi-tenancy boundaries
    location_filter = Customer.location_id == current_user.location_id if not current_user.is_superuser else True
    
    device_stmt = db.select(Device).join(Customer).where(
        Customer.id == customer_id, location_filter
    )
    if query:
        device_stmt = device_stmt.where(or_(Device.brand.ilike(f'%{query}%'), Device.model_number.ilike(f'%{query}%')))
    devices = db.session.scalars(device_stmt.limit(10)).all()
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
        color=request.form.get('color'),
        notes=request.form.get('notes')
    )
    if success:
        try:
            db.session.commit()
            return jsonify({'id': result.id, 'display': result.display})
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"AJAX device creation database error: {str(e)}")
            return jsonify({'error': _('A database error occurred.')}), 500
    return jsonify({'error': result}), 400