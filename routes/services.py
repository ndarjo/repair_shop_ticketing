from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from models import Location, Service, TicketService, db
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

    locations = []
    if current_user.is_superuser:
        # UI CONSISTENCY: Align branch switching permissions with the inventory module
        locations = db.session.scalars(db.select(Location).order_by(Location.name)).all()
        location_filter = (Service.location_id == selected_location) if selected_location else True
    else:
        location_filter = (Service.location_id == current_user.location_id)

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
    page = request.args.get('page', 1, type=int)
    query = request.args.get('q', '').strip()
    name = request.form.get('name', '').strip()
    price = safe_decimal(request.form.get('price', '0.00'))
    selected_location = request.args.get('location_id', type=int)
    
    if not name:
        flash(_('Service name is required.'), 'danger')
        return render_template('services/manage_services.html', services=db.paginate(db.select(Service).order_by(Service.name), page=page, per_page=15),
                               search_query=query, locations=db.session.scalars(db.select(Location).order_by(Location.name)).all() if current_user.is_superuser else [],
                               selected_location=selected_location,
                               name=name, description=request.form.get('description', ''), price=price)

    # UI CONSISTENCY: Allow admins to target a specific branch while filtering
    loc_id = selected_location if (current_user.is_superuser and selected_location) else current_user.location_id
    if not loc_id:
        loc_id = db.session.scalar(db.select(Location.id).limit(1))

    # Integrity: Check for duplicate services at this location
    exists = db.session.scalar(db.select(Service).where(
        func.lower(Service.name) == func.lower(name),
        Service.location_id == loc_id
    ))
    if exists:
        flash(_('A service with this name already exists in your catalog.'), 'danger')
        return render_template('services/manage_services.html', services=db.paginate(db.select(Service).order_by(Service.name), page=page, per_page=15),
                               search_query=query, locations=db.session.scalars(db.select(Location).order_by(Location.name)).all() if current_user.is_superuser else [],
                               selected_location=selected_location,
                               name=name, description=request.form.get('description', ''), price=price)

    if price < 0:
        flash(_('Service price cannot be negative.'), 'danger')
        return render_template('services/manage_services.html', services=db.paginate(db.select(Service).order_by(Service.name), page=page, per_page=15),
                               search_query=query, locations=db.session.scalars(db.select(Location).order_by(Location.name)).all() if current_user.is_superuser else [],
                               selected_location=selected_location,
                               name=name, description=request.form.get('description', ''), price=price)
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
        return redirect(url_for('services.manage_services', location_id=selected_location))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Service addition error: {str(e)}")
        flash(_('Error adding service to catalog.'), 'danger')
        return render_template('services/manage_services.html', services=db.paginate(db.select(Service).order_by(Service.name), page=page, per_page=15),
                               search_query=query, locations=db.session.scalars(db.select(Location).order_by(Location.name)).all() if current_user.is_superuser else [],
                               selected_location=selected_location,
                               name=name, description=request.form.get('description', ''), price=price)


@services_bp.route('/edit/<int:service_id>', methods=['POST'])
@login_required
@require_permission('manage_settings')
def edit_service(service_id):
    """Endpoint for the dynamic edit modal"""
    page = request.args.get('page', 1, type=int)
    query = request.args.get('q', '').strip()
    service = db.session.get(Service, service_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    selected_location = request.args.get('location_id', type=int)
    
    locations_for_template = db.session.scalars(db.select(Location).order_by(Location.name)).all() if current_user.is_superuser else []

    if not service or (not is_admin and service.location_id != current_user.location_id):
        flash(_('Service not found.'), 'danger')
        return redirect(url_for('services.manage_services', location_id=selected_location))

    name = request.form.get('name', '').strip()
    price = safe_decimal(request.form.get('price', '0.00'))

    if not name:
        flash(_('Service name is required.'), 'danger')
        return render_template('services/manage_services.html', services=db.paginate(db.select(Service).order_by(Service.name), page=page, per_page=15),
                               search_query=query, locations=locations_for_template, selected_location=selected_location,
                               service=service, name=name, description=request.form.get('description', ''),
                               price=price, is_active='is_active' in request.form)

    # Integrity: Check for duplicate services (excluding current) at this location
    exists = db.session.scalar(db.select(Service).where(
        func.lower(Service.name) == func.lower(name),
        Service.location_id == service.location_id,
        Service.id != service_id
    ))
    if exists:
        flash(_('Another service already uses this name.'), 'danger')
        return render_template('services/manage_services.html', services=db.paginate(db.select(Service).order_by(Service.name), page=page, per_page=15),
                               search_query=query, locations=locations_for_template, selected_location=selected_location,
                               service=service, name=name, description=request.form.get('description', ''),
                               price=price, is_active='is_active' in request.form)

    if price < 0:
        flash(_('Service price cannot be negative.'), 'danger')
        return render_template('services/manage_services.html', services=db.paginate(db.select(Service).order_by(Service.name), page=page, per_page=15),
                               search_query=query, locations=locations_for_template, selected_location=selected_location,
                               service=service, name=name, description=request.form.get('description', ''),
                               price=price, is_active='is_active' in request.form)

    service.name = name
    service.description = request.form.get('description', '')
    service.price = price
    service.is_active = 'is_active' in request.form
    
    try:
        db.session.commit()
        flash(_('Service updated.'), 'success')
        return redirect(url_for('services.manage_services', location_id=selected_location))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Service update error: {str(e)}")
        flash(_('Error updating service.'), 'danger')
        # UX Integrity: Return form data on error to prevent data loss
        return render_template('services/manage_services.html', services=db.paginate(db.select(Service).order_by(Service.name), page=page, per_page=15),
                               search_query=query, locations=locations_for_template, selected_location=selected_location,
                               service=service, name=name, description=request.form.get('description', ''),
                               price=price, is_active='is_active' in request.form)

@services_bp.route('/delete/<int:service_id>', methods=['POST'])
@login_required
@require_permission('manage_settings')
def delete_service(service_id):
    """Permanent removal of service from catalog"""
    selected_location = request.args.get('location_id', type=int)

    service = db.session.get(Service, service_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if service and (is_admin or service.location_id == current_user.location_id):
        # INTEGRITY: Check for linked TicketService records before deletion
        linked_ticket_services = db.session.scalar(db.select(func.count(TicketService.id)).where(TicketService.service_id == service_id))
        if linked_ticket_services > 0:
            flash(_('Cannot delete service: It is linked to existing tickets. Deactivate it instead.'), 'danger')
            return redirect(url_for('services.manage_services', location_id=selected_location))

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
    return redirect(url_for('services.manage_services', location_id=selected_location))