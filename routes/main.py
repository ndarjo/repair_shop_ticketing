from datetime import datetime, timezone

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import joinedload, selectinload

from models import CommonProblem, Customer, Location, Ticket, db
from .utils import require_permission

# Create blueprints cleanly
main_bp = Blueprint('main', __name__)

# ==================== MAIN ROUTES ====================
@main_bp.route('/')
@main_bp.route('/dashboard')
@login_required
def dashboard():
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    page = request.args.get('page', 1, type=int)
    selected_location = request.args.get('location_id', type=int)
    
    # SCALABILITY: Scoped query for multi-location support
    if current_user.is_superuser:
        # SCALABILITY: Superusers can toggle global views or filter by branch
        location_filter = (Ticket.location_id == selected_location) if selected_location else True
        customer_filter = (Customer.location_id == selected_location) if selected_location else True
    else:
        # INTEGRITY: Enforce multi-tenancy boundaries for all other roles
        location_filter = (Ticket.location_id == current_user.location_id)
        customer_filter = (Customer.location_id == current_user.location_id)
    
    # INTEGRITY: Define the standard "Active" filter to ensure UI consistency 
    # between the ticket list and the summary status counts.
    active_filter = [
        location_filter, 
        Ticket.is_archived.is_(False), 
        Ticket.current_phase.notin_(['Already Taken', 'Cancelled'])
    ]

    stmt = db.select(Ticket).options(
        joinedload(Ticket.customer), 
        joinedload(Ticket.device),
        selectinload(Ticket.invoices)
    ).where(*active_filter).order_by(desc(Ticket.created_at))
    
    tickets = db.paginate(stmt, page=page, per_page=10, error_out=False)
    active_total = tickets.total
    
    # Single aggregate query for status counts, synced with active tickets only
    phase_counts_stmt = db.select(
        Ticket.current_phase, func.count(Ticket.id)
    ).where(*active_filter).group_by(Ticket.current_phase)
    phase_counts = db.session.execute(phase_counts_stmt).all()
    phase_map = dict(phase_counts)

    # Integrity: Filter out anonymized and deleted users from counts and selection
    active_cust_filter = (Customer.is_anonymized.is_(False)) & (~Customer.name.ilike('DELETED_USER_%'))
    customer_count_stmt = db.select(func.count(Customer.id)).where(customer_filter, active_cust_filter)

    # Fetch customers for the dashboard quick sale widget
    customers = db.session.scalars(db.select(Customer).where(customer_filter, active_cust_filter).order_by(Customer.name).limit(50)).all()

    stats = {
        'total_tickets': active_total,
        'open_tickets': phase_map.get('Open', 0),
        'diagnostic': phase_map.get('Diagnostic', 0),
        'repairing': phase_map.get('Repairing', 0),
        'finished': phase_map.get('Finished', 0),
        'total_customers': db.session.scalar(customer_count_stmt) or 0
    }
    
    locations = []
    if is_admin:
        locations = db.session.scalars(db.select(Location).order_by(Location.name)).all()
    
    return render_template('main/dashboard.html', tickets=tickets, stats=stats, customers=customers, locations=locations, selected_location=selected_location)

@main_bp.route('/health')
def health_check():
    """Lightweight endpoint for monitoring and load balancers"""
    try:
        # INTEGRITY: Use a simple query to verify DB connectivity
        db.session.execute(db.select(1)).scalar()
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'version': '1.0.0'
        }), 200
    except Exception as e:
        current_app.logger.critical(f"Health check failed: {str(e)}")
        return jsonify({'status': 'unhealthy', 'error': _('Database unreachable')}), 503

@main_bp.route('/common-problems', methods=['GET', 'POST'])
@login_required
@require_permission('admin_manage_common_problems')
def manage_common_problems():
    page = request.args.get('page', 1, type=int)
    selected_location = request.args.get('location_id', type=int)
    locations_for_template = db.session.scalars(db.select(Location).order_by(Location.name)).all() if current_user.is_superuser else []
    location_filter = (CommonProblem.location_id == selected_location) if selected_location else True if current_user.is_superuser else or_(CommonProblem.location_id == current_user.location_id, CommonProblem.location_id == None)
    problems_for_template = db.paginate(db.select(CommonProblem).where(location_filter).order_by(CommonProblem.created_at.desc()), page=page, per_page=15, error_out=False)

    if request.method == 'POST':
        problem_text = request.form.get('problem_text', '').strip() # Retrieve once
        selected_location = request.args.get('location_id', type=int) # Retrieve once

        if problem_text:
            # INTEGRITY: Branch managers are locked to their own branch location.
            if current_user.is_superuser:
                loc_id = selected_location
            else:
                loc_id = current_user.location_id

            # Integrity: Handle duplicate quick-select options
            exists = db.session.scalar(db.select(CommonProblem).where(
                func.lower(CommonProblem.problem_text) == func.lower(problem_text),
                CommonProblem.location_id == loc_id
            ))
            if exists:
                flash(_('This problem description already exists.'), 'danger')
                return render_template('common_problem/manage_common_problems.html', problems=problems_for_template,
                                       locations=locations_for_template, selected_location=selected_location,
                                       problem_text=problem_text)
            else:
                new_prob = CommonProblem(problem_text=problem_text, location_id=loc_id)
                db.session.add(new_prob)
                try:
                    db.session.commit()
                    flash(_('Common problem added.'), 'success')
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Problem creation error: {str(e)}")
                    flash(_('Error adding problem to the database.'), 'danger')
                    return render_template('common_problem/manage_common_problems.html', problems=problems_for_template,
                                           locations=locations_for_template, selected_location=selected_location,
                                           problem_text=problem_text)
        else:
            flash(_('Problem description cannot be empty.'), 'danger')
            return render_template('common_problem/manage_common_problems.html', problems=problems_for_template,
                                   locations=locations_for_template, selected_location=selected_location,
                                   problem_text=problem_text)
        return redirect(url_for('main.manage_common_problems', location_id=selected_location)) # Redirect on success
    
    return render_template('common_problem/manage_common_problems.html',
                           problems=problems_for_template,
                           locations=locations_for_template,
                           selected_location=selected_location)

@main_bp.route('/common-problems/delete/<int:problem_id>', methods=['POST'])
@login_required
@require_permission('admin_manage_common_problems')
def delete_problem(problem_id):
    """Dedicated route for removing common problems"""
    location_id = request.args.get('location_id', type=int)
    page = request.args.get('page', 1, type=int)

    prob = db.session.get(CommonProblem, problem_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if prob and (is_admin or prob.location_id == current_user.location_id):
        # INTEGRITY: Check for linked Ticket records before deletion
        linked_tickets = db.session.scalar(db.select(func.count(Ticket.id)).where(Ticket.problem_description.ilike(f'%{prob.problem_text}%')))
        if linked_tickets > 0:
            flash(_('Cannot delete common problem: It is referenced in existing tickets. Consider editing or deactivating it instead.'), 'danger')
            return redirect(url_for('main.manage_common_problems', location_id=location_id, page=page))

        try:
            db.session.delete(prob)
            db.session.commit()
            flash(_('Problem removed.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Problem deletion error: {str(e)}")
            flash(_('Error removing problem.'), 'danger')
    else:
        flash(_('Problem not found or access denied.'), 'danger')
    return redirect(url_for('main.manage_common_problems', location_id=location_id, page=page))