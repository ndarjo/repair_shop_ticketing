from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, timezone
from sqlalchemy import desc, func, select
from sqlalchemy.orm import joinedload
from models import db, Customer, Ticket
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
    
    # FIXED: Filter out tickets that have already been picked up by customers
    stmt = select(Ticket).options(
        joinedload(Ticket.customer), 
        joinedload(Ticket.device)
    ).where(location_filter, Ticket.current_phase != 'Already Taken', Ticket.is_archived == False).order_by(desc(Ticket.created_at))
    
    tickets = db.paginate(stmt, page=page, per_page=10)
    
    # Single aggregate query for status counts
    phase_counts = db.session.query(
        Ticket.current_phase, func.count(Ticket.id)
    ).filter(location_filter, Ticket.is_archived == False).group_by(Ticket.current_phase).all()
    phase_map = dict(phase_counts)

    # Calculate total active tickets from the phase_map to save a DB query
    active_total = sum(count for phase, count in phase_counts if phase != 'Already Taken')

    stats = {
        'total_tickets': active_total,
        'open_tickets': phase_map.get('Open', 0),
        'diagnostic': phase_map.get('Diagnostic', 0),
        'repairing': phase_map.get('Repairing', 0),
        'finished': phase_map.get('Finished', 0),
        'total_customers': Customer.query.filter(Customer.location_id == current_user.location_id).count() if not current_user.is_superuser else Customer.query.count(),
    }
    
    return render_template('dashboard.html', tickets=tickets, stats=stats, current_theme=current_user.theme_preference)

@main_bp.route('/health')
def health_check():
    """Lightweight endpoint for monitoring and load balancers"""
    try:
        # Simple query to verify DB connectivity
        db.session.execute(func.now())
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'version': '1.0.0'
        }), 200
    except Exception as e:
        current_app.logger.critical(f"Health check failed: {str(e)}")
        return jsonify({'status': 'unhealthy', 'error': 'Database unreachable'}), 503