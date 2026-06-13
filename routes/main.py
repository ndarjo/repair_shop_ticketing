from flask import Blueprint, render_template, request, jsonify, current_app, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime
from sqlalchemy import desc, func, select
from sqlalchemy.orm import joinedload
from models import db, Customer, Ticket, CommonProblem, SparePart, Service, Location
from .utils import require_permission, safe_decimal
from flask_babel import _

# Create blueprints cleanly
main_bp = Blueprint('main', __name__)

# ==================== MAIN ROUTES ====================
@main_bp.route('/')
@main_bp.route('/dashboard')
@login_required
def dashboard():
    page = request.args.get('page', 1, type=int)
    
    # SCALABILITY: Scoped query for multi-location support
    location_filter = Ticket.location_id == current_user.location_id if not current_user.is_superuser else True
    
    # INTEGRITY: Filter out tickets that have already been picked up or cancelled
    stmt = select(Ticket).options(
        joinedload(Ticket.customer), 
        joinedload(Ticket.device)
    ).where(location_filter, Ticket.current_phase.notin_(['Already Taken', 'Cancelled']), Ticket.is_archived == False).order_by(desc(Ticket.created_at))
    
    tickets = db.paginate(stmt, page=page, per_page=10)
    
    # Single aggregate query for status counts
    phase_counts_stmt = db.select(
        Ticket.current_phase, func.count(Ticket.id)
    ).where(location_filter, Ticket.is_archived == False).group_by(Ticket.current_phase)
    phase_counts = db.session.execute(phase_counts_stmt).all()
    phase_map = dict(phase_counts)

    # Calculate total active tickets from the phase_map to save a DB query
    active_total = sum(count for phase, count in phase_counts if phase not in ['Already Taken', 'Cancelled'])

    customer_filter = Customer.location_id == current_user.location_id if not current_user.is_superuser else True
    customer_count_stmt = select(func.count(Customer.id)).where(customer_filter)

    stats = {
        'total_tickets': active_total,
        'open_tickets': phase_map.get('Open', 0),
        'diagnostic': phase_map.get('Diagnostic', 0),
        'repairing': phase_map.get('Repairing', 0),
        'finished': phase_map.get('Finished', 0),
        'total_customers': db.session.scalar(customer_count_stmt) or 0,
    }
    
    return render_template('main/dashboard.html', tickets=tickets, stats=stats)

@main_bp.route('/health')
def health_check():
    """Lightweight endpoint for monitoring and load balancers"""
    try:
        # Simple query to verify DB connectivity
        db.session.execute(select(func.now())).scalar()
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'version': '1.0.0'
        }), 200
    except Exception as e:
        current_app.logger.critical(f"Health check failed: {str(e)}")
        return jsonify({'status': 'unhealthy', 'error': 'Database unreachable'}), 503

@main_bp.route('/common-problems', methods=['GET', 'POST'])
@login_required
@require_permission('manage_settings')
def manage_common_problems():
    if request.method == 'POST':
        problem_text = request.form.get('problem_text', '').strip()
        if problem_text:
            # SCALABILITY: Use user's location or fallback to primary branch for global admins
            loc_id = current_user.location_id or db.session.scalar(select(Location.id).limit(1))
            # Integrity: Handle duplicate quick-select options
            exists = db.session.scalar(select(CommonProblem).where(
                func.lower(CommonProblem.problem_text) == func.lower(problem_text),
                CommonProblem.location_id == loc_id
            ))
            if exists:
                flash(_('This problem description already exists.'), 'warning')
                return redirect(url_for('main.manage_common_problems'))

            new_prob = CommonProblem(problem_text=problem_text, location_id=loc_id)
            db.session.add(new_prob)
            try:
                db.session.commit()
                flash(_('Common problem added.'), 'success')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Problem creation error: {str(e)}")
                flash(_('Error adding problem to database.'), 'error')
            return redirect(url_for('main.manage_common_problems'))
    
    page = request.args.get('page', 1, type=int)
    location_filter = CommonProblem.location_id == current_user.location_id if not current_user.is_superuser else True
    stmt = db.select(CommonProblem).where(location_filter).order_by(CommonProblem.created_at.desc())
    problems = db.paginate(stmt, page=page, per_page=15)
    
    return render_template('common_problem/manage_common_problems.html', problems=problems)

@main_bp.route('/common-problems/delete/<int:problem_id>', methods=['POST'])
@login_required
@require_permission('manage_settings')
def delete_problem(problem_id):
    """Dedicated route for removing common problems"""
    prob = db.session.get(CommonProblem, problem_id)
    if prob and (current_user.is_superuser or prob.location_id == current_user.location_id):
        try:
            db.session.delete(prob)
            db.session.commit()
            flash(_('Problem removed.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Problem deletion error: {str(e)}")
            flash(_('Error removing problem.'), 'error')
    return redirect(url_for('main.manage_common_problems'))

@main_bp.route('/inventory')
@login_required
@require_permission('manage_inventory')
def manage_inventory():
    """Dedicated inventory management for spare parts and stock levels"""
    page = request.args.get('page', 1, type=int)
    location_filter = SparePart.location_id == current_user.location_id if not current_user.is_superuser else True
    stmt = db.select(SparePart).where(location_filter).order_by(SparePart.name)
    parts = db.paginate(stmt, page=page, per_page=15)
    return render_template('parts/manage_parts.html', parts=parts)

@main_bp.route('/inventory/add', methods=['POST'])
@login_required
@require_permission('manage_inventory')
def add_part():
    """Endpoint for creating a new catalog part"""
    name = request.form.get('name', '').strip()
    stock = request.form.get('stock_quantity', 0, type=int)
    
    if not name:
        flash(_('Part name is required.'), 'error')
        return redirect(url_for('main.manage_inventory'))

    loc_id = current_user.location_id or db.session.scalar(select(Location.id).limit(1))

    # Integrity: Check for duplicate names at this location
    exists = db.session.scalar(select(SparePart).where(
        func.lower(SparePart.name) == func.lower(name),
        SparePart.location_id == loc_id
    ))
    if exists:
        flash(_('A part with this name already exists in your inventory.'), 'warning')
        return redirect(url_for('main.manage_inventory'))

    cost = safe_decimal(request.form.get('cost', '0.00'))
    selling_price = safe_decimal(request.form.get('selling_price', '0.00'))

    if stock < 0 or cost < 0 or selling_price < 0:
        flash(_('Stock, cost, and price cannot be negative.'), 'error')
        return redirect(url_for('main.manage_inventory'))

    new_part = SparePart(
        name=name,
        cost=cost,
        selling_price=selling_price,
        stock_quantity=stock,
        location_id=loc_id
    )
    db.session.add(new_part)
    try:
        db.session.commit()
        flash(_('New part added to inventory.'), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Part addition error: {str(e)}")
        flash(_('Error adding part to inventory.'), 'error')
    return redirect(url_for('main.manage_inventory'))

@main_bp.route('/inventory/edit/<int:part_id>', methods=['POST'])
@login_required
@require_permission('manage_inventory')
def edit_part(part_id):
    """Endpoint for updating existing part specifications"""
    part = db.session.get(SparePart, part_id)
    if not part or (not current_user.is_superuser and part.location_id != current_user.location_id):
        flash(_('Part not found.'), 'error')
        return redirect(url_for('main.manage_inventory'))

    name = request.form.get('name', '').strip()
    stock = request.form.get('stock_quantity', 0, type=int)

    if not name:
        flash(_('Part name is required.'), 'error')
        return redirect(url_for('main.manage_inventory'))

    # Integrity: Check for duplicate names (excluding current part) at this location
    exists = db.session.scalar(select(SparePart).where(
        func.lower(SparePart.name) == func.lower(name),
        SparePart.location_id == part.location_id,
        SparePart.id != part_id
    ))
    if exists:
        flash(_('Another part already uses this name.'), 'warning')
        return redirect(url_for('main.manage_inventory'))

    cost = safe_decimal(request.form.get('cost', '0.00'))
    selling_price = safe_decimal(request.form.get('selling_price', '0.00'))

    if stock < 0 or cost < 0 or selling_price < 0:
        flash(_('Stock, cost, and price cannot be negative.'), 'error')
        return redirect(url_for('main.manage_inventory'))

    part.name = name
    part.cost = cost
    part.selling_price = selling_price
    part.stock_quantity = stock
    part.is_active = 'is_active' in request.form
    
    try:
        db.session.commit()
        flash(_('Inventory item updated.'), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Part update error: {str(e)}")
        flash(_('Error updating inventory item.'), 'error')
    return redirect(url_for('main.manage_inventory'))

@main_bp.route('/inventory/delete/<int:part_id>', methods=['POST'])
@login_required
@require_permission('manage_inventory')
def delete_part(part_id):
    """Endpoint for permanent removal of inventory items"""
    part = db.session.get(SparePart, part_id)
    if part and (current_user.is_superuser or part.location_id == current_user.location_id):
        try:
            db.session.delete(part)
            db.session.commit()
            flash(_('Part deleted.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Part deletion error: {str(e)}")
            flash(_('Error deleting part. It may be linked to existing tickets.'), 'error')
    return redirect(url_for('main.manage_inventory'))

@main_bp.route('/services')
@login_required
@require_permission('manage_settings')
def manage_services():
    """Catalog of labor services offered by the shop"""
    page = request.args.get('page', 1, type=int)
    location_filter = Service.location_id == current_user.location_id if not current_user.is_superuser else True
    stmt = db.select(Service).where(location_filter).order_by(Service.name)
    services = db.paginate(stmt, page=page, per_page=15)
    return render_template('services/manage_services.html', services=services)

@main_bp.route('/services/add', methods=['POST'])
@login_required
@require_permission('manage_settings')
def add_service():
    """Endpoint to add a new service to the catalog"""
    name = request.form.get('name', '').strip()
    if not name:
        flash(_('Service name is required.'), 'error')
        return redirect(url_for('main.manage_services'))

    loc_id = current_user.location_id or db.session.scalar(select(Location.id).limit(1))

    # Integrity: Check for duplicate services at this location
    exists = db.session.scalar(select(Service).where(
        func.lower(Service.name) == func.lower(name),
        Service.location_id == loc_id
    ))
    if exists:
        flash(_('A service with this name already exists in your catalog.'), 'warning')
        return redirect(url_for('main.manage_services'))

    price = safe_decimal(request.form.get('price', '0.00'))
    if price < 0:
        flash(_('Service price cannot be negative.'), 'error')
        return redirect(url_for('main.manage_services'))

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
        flash(_('Error adding service to catalog.'), 'error')
    return redirect(url_for('main.manage_services'))

@main_bp.route('/services/edit/<int:service_id>', methods=['POST'])
@login_required
@require_permission('manage_settings')
def edit_service(service_id):
    """Endpoint for the dynamic edit modal in main.js"""
    service = db.session.get(Service, service_id)
    if not service or (not current_user.is_superuser and service.location_id != current_user.location_id):
        flash(_('Service not found.'), 'error')
        return redirect(url_for('main.manage_services'))

    name = request.form.get('name', '').strip()
    if not name:
        flash(_('Service name is required.'), 'error')
        return redirect(url_for('main.manage_services'))

    # Integrity: Check for duplicate services (excluding current) at this location
    exists = db.session.scalar(select(Service).where(
        func.lower(Service.name) == func.lower(name),
        Service.location_id == service.location_id,
        Service.id != service_id
    ))
    if exists:
        flash(_('Another service already uses this name.'), 'warning')
        return redirect(url_for('main.manage_services'))

    price = safe_decimal(request.form.get('price', '0.00'))
    if price < 0:
        flash(_('Service price cannot be negative.'), 'error')
        return redirect(url_for('main.manage_services'))

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
        flash(_('Error updating service.'), 'error')
    return redirect(url_for('main.manage_services'))

@main_bp.route('/services/delete/<int:service_id>', methods=['POST'])
@login_required
@require_permission('manage_settings')
def delete_service(service_id):
    """Permanent removal of service from catalog"""
    service = db.session.get(Service, service_id)
    if service and (current_user.is_superuser or service.location_id == current_user.location_id):
        try:
            db.session.delete(service)
            db.session.commit()
            flash(_('Service deleted.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Service deletion error: {str(e)}")
            flash(_('Error deleting service. It may be linked to existing tickets.'), 'error')
    return redirect(url_for('main.manage_services'))