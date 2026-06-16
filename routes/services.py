from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from models import Location, Service, db
from .utils import require_permission, safe_decimal

services_bp = Blueprint('services', __name__)

@services_bp.route('/')
@login_required
@require_permission('view_services')
def manage_services():
    """Catalog of labor services offered by the shop"""
    page = request.args.get('page', 1, type=int)
    query = request.args.get('q', '').strip()
    selected_location = request.args.get('location_id', type=int)

    is_admin = current_user.is_superuser or current_user.has_role('admin')

    locations = []
    if current_user.is_superuser:
        # Fetch all locations for the filter dropdown (Superusers only)
        locations = db.session.scalars(db.select(Location).order_by(Location.name)).all()
        location_filter = (Service.location_id == selected_location) if selected_location else True
    else:
        # Multi-tenancy: Staff see their branch, Admins (non-superuser) see all by default
        location_filter = Service.location_id == current_user.location_id if not is_admin else True

    stmt = db.select(Service).where(location_filter)

    if query:
        stmt = stmt.where(or_(
            Service.name.ilike(f'%{query}%'),
            Service.description.ilike(f'%{query}%')
        ))

    stmt = stmt.order_by(Service.name)
    services = db.paginate(stmt, page=page, per_page=15)
    return render_template('services/manage_services.html', 
                           services=services, 
                           search_query=query, 
                           locations=locations, 
                           selected_location=selected_location)

@services_bp.route('/add', methods=['POST'])
@login_required
@require_permission('manage_settings')
def add_service():
    """Endpoint to add a new service to the catalog"""
    name = request.form.get('name', '').strip()
    if not name:
        flash(_('Service name is required.'), 'danger')
        return redirect(url_for('services.manage_services'))

    loc_id = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))

    # Integrity: Check for duplicate services at this location
    exists = db.session.scalar(db.select(Service).where(
        func.lower(Service.name) == func.lower(name),
        Service.location_id == loc_id
    ))
    if exists:
        flash(_('A service with this name already exists in your catalog.'), 'danger')
        return redirect(url_for('services.manage_services'))

    price = safe_decimal(request.form.get('price', '0.00'))
    if price < 0:
        flash(_('Service price cannot be negative.'), 'danger')
        return redirect(url_for('services.manage_services'))

    new_service = Service(
        name=name,
        description=request.form.get('description', ''),
        price=price,
        location_id=loc_id
    )
    db.session.add(new_service)
    try:
        db.session.commit()
        flash(_('Service added to catalog.'), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Service addition error: {str(e)}")
        flash(_('Error adding service to catalog.'), 'danger')
    return redirect(url_for('services.manage_services'))

@services_bp.route('/edit/<int:service_id>', methods=['POST'])
@login_required
@require_permission('manage_settings')
def edit_service(service_id):
    """Endpoint for the dynamic edit modal"""
    service = db.session.get(Service, service_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not service or (not is_admin and service.location_id != current_user.location_id):
        flash(_('Service not found.'), 'danger')
        return redirect(url_for('services.manage_services'))

    name = request.form.get('name', '').strip()
    if not name:
        flash(_('Service name is required.'), 'danger')
        return redirect(url_for('services.manage_services'))

    # Integrity: Check for duplicate services (excluding current) at this location
    exists = db.session.scalar(db.select(Service).where(
        func.lower(Service.name) == func.lower(name),
        Service.location_id == service.location_id,
        Service.id != service_id
    ))
    if exists:
        flash(_('Another service already uses this name.'), 'danger')
        return redirect(url_for('services.manage_services'))

    price = safe_decimal(request.form.get('price', '0.00'))
    if price < 0:
        flash(_('Service price cannot be negative.'), 'danger')
        return redirect(url_for('services.manage_services'))

    service.name = name
    service.description = request.form.get('description', '')
    service.price = price
    service.is_active = 'is_active' in request.form
    
    try:
        db.session.commit()
        flash(_('Service updated.'), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Service update error: {str(e)}")
        flash(_('Error updating service.'), 'danger')
    return redirect(url_for('services.manage_services'))

@services_bp.route('/delete/<int:service_id>', methods=['POST'])
@login_required
@require_permission('manage_settings')
def delete_service(service_id):
    """Permanent removal of service from catalog"""
    service = db.session.get(Service, service_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if service and (is_admin or service.location_id == current_user.location_id):
        try:
            db.session.delete(service)
            db.session.commit()
            flash(_('Service deleted.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Service deletion error: {str(e)}")
            flash(_('Error deleting service. It may be linked to existing tickets.'), 'danger')
    else:
        flash(_('Service not found or access denied.'), 'danger')
    return redirect(url_for('services.manage_services'))