from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user, login_user, logout_user
from datetime import datetime, timezone
from sqlalchemy import desc, or_, func
from models import db, User, Role, Permission, Customer, Device, Ticket, Note, Payment, PhaseLog, Service, SparePart, Invoice, InvoiceItem, TicketService, CommonProblem
from decimal import Decimal
import uuid
from functools import wraps
import json
import io
import os

# Create blueprints cleanly
auth_bp = Blueprint('auth', __name__)
main_bp = Blueprint('main', __name__)
ticket_bp = Blueprint('ticket', __name__)
customer_bp = Blueprint('customer', __name__)
admin_bp = Blueprint('admin', __name__)
report_bp = Blueprint('report', __name__)
device_bp = Blueprint('device', __name__)


# ==================== PERMISSION DECORATORS ====================
def require_permission(permission_name):
    """Decorator to check if user has specific permission"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': 'Authentication required'}), 401
                flash('Please log in first.', 'error')
                return redirect(url_for('auth.login'))
            if not current_user.has_permission(permission_name):
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': 'Permission denied'}), 403
                flash('You do not have permission to access this page.', 'error')
                return redirect(url_for('main.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_superuser():
    """Decorator to check if user is superuser"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in first.', 'error')
                return redirect(url_for('auth.login'))
            if not current_user.is_superuser:
                flash('You do not have permission to access this page.', 'error')
                return redirect(url_for('main.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==================== AUTH ROUTES ====================
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password) and user.is_active:
            login_user(user)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('main.dashboard'))
        else:
            flash('Invalid username or password', 'error')
    
    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile - change username, password, and theme"""
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'change_username':
            new_username = request.form.get('new_username')
            if User.query.filter_by(username=new_username).first():
                flash('Username already exists', 'error')
            else:
                current_user.username = new_username
                db.session.commit()
                flash('Username changed successfully!', 'success')
        
        elif action == 'change_password':
            old_password = request.form.get('old_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            if not current_user.check_password(old_password):
                flash('Current password is incorrect', 'error')
            elif new_password != confirm_password:
                flash('New passwords do not match', 'error')
            elif len(new_password) < 6:
                flash('Password must be at least 6 characters', 'error')
            else:
                current_user.set_password(new_password)
                db.session.commit()
                flash('Password changed successfully!', 'success')
        
        elif action == 'change_theme':
            theme = request.form.get('theme')
            color = request.form.get('color_theme')
            if theme in ['light', 'dark']:
                current_user.theme_preference = theme
            if color in ['blue', 'green', 'purple', 'red', 'orange']:
                current_user.color_theme = color

            # Restrict currency settings to superuser or manager
            if current_user.is_superuser or current_user.has_role('manager'):
                currency = request.form.get('currency')
                currency_decimals = request.form.get('currency_decimals', type=int)
                if currency in ['USD', 'IDR', 'EUR', 'GBP']:
                    current_user.currency = currency
                if currency_decimals is not None and 0 <= currency_decimals <= 4:
                    current_user.currency_decimals = currency_decimals

            db.session.commit()
            flash('Preferences updated successfully!', 'success')
        
        return redirect(url_for('auth.profile'))
    
    return render_template('profile.html')


# ==================== MAIN ROUTES ====================
@main_bp.route('/')
@main_bp.route('/dashboard')
@login_required
def dashboard():
    page = request.args.get('page', 1, type=int)
    
    # FIXED: Filter out tickets that have already been picked up by customers
    query = Ticket.query.filter(Ticket.current_phase != 'Already Taken').order_by(desc(Ticket.created_at))
    tickets = query.paginate(page=page, per_page=10)
    
    # Single aggregate query for status counts
    phase_counts = db.session.query(
        Ticket.current_phase, func.count(Ticket.id)
    ).group_by(Ticket.current_phase).all()
    phase_map = dict(phase_counts)

    stats = {
        'total_tickets': Ticket.query.count(),
        'open_tickets': phase_map.get('Open', 0),
        'diagnostic': phase_map.get('Diagnostic', 0),
        'repairing': phase_map.get('Repairing', 0),
        'finished': phase_map.get('Finished', 0),
        'total_customers': Customer.query.count(),
    }
    
    return render_template('dashboard.html', tickets=tickets, stats=stats, current_theme=current_user.theme_preference)


# ==================== TICKET ROUTES ====================
@ticket_bp.route('/')
@login_required
@require_permission('view_ticket')
def tickets_list():
    """Dedicated page for all tickets with full pagination"""
    view = request.args.get('view', 'active')
    page = request.args.get('page', 1, type=int)
    
    if view == 'history':
        # Show only picked up devices
        query = Ticket.query.filter_by(current_phase='Already Taken')
    else:
        # Show everything currently in the shop
        query = Ticket.query.filter(Ticket.current_phase != 'Already Taken')
        
    query = query.order_by(desc(Ticket.created_at))
    tickets = query.paginate(page=page, per_page=20)
    return render_template('tickets_list.html', tickets=tickets, current_view=view)

@ticket_bp.route('/new', methods=['GET', 'POST'])
@login_required
@require_permission('create_ticket')
def new_ticket():
    customers = Customer.query.order_by(desc(Customer.created_at)).all()
    users = User.query.filter(User.roles.any(Role.name == 'technician')).all()
    common_problems = CommonProblem.query.filter_by(is_active=True).all()
    
    # Calculate default values for the form
    now = datetime.now(timezone.utc)
    now_date = now.strftime('%Y-%m-%d')
    now_time = now.strftime('%H:%M')
    
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        device_id = request.form.get('device_id')
        items_included = request.form.get('items_included', '')
        problem_description = request.form.get('problem_description', '')
        assigned_to = request.form.get('assigned_to')
        created_date = request.form.get('created_date')
        created_time = request.form.get('created_time')
        
        # Financial fields from form
        down_payment = max(0, request.form.get('down_payment_amount', 0, type=float))
        payment_method = request.form.get('payment_method')
        
        if not device_id:
            flash('Please select a device', 'error')
            return redirect(url_for('ticket.new_ticket'))
        
        # Verify device ownership to prevent data mismatch
        device = db.session.get(Device, device_id)
        if not device or str(device.customer_id) != str(customer_id):
            flash('Security Error: Selected device does not belong to the selected customer.', 'error')
            return redirect(url_for('ticket.new_ticket'))

        try:
            created_datetime = datetime.strptime(f"{created_date} {created_time}", "%Y-%m-%d %H:%M")
        except (ValueError, TypeError):
            created_datetime = datetime.now(timezone.utc)
        
        ticket_number = Ticket.generate_unique_number()

        try:
            ticket = Ticket(
                ticket_number=ticket_number,
                customer_id=customer_id,
                device_id=device_id,
                items_included=items_included,
                problem_description=problem_description,
                assigned_to=assigned_to if assigned_to else None,
                created_at=created_datetime
            )
            db.session.add(ticket)
            db.session.flush() # Secure ID assignment prior to child creations
            
            initial_log = PhaseLog(
                ticket_id=ticket.id,
                user_id=current_user.id,
                old_phase=None,
                new_phase='Open'
            )
            db.session.add(initial_log)

            # Handle optional down payment
            if down_payment > 0:
                payment = Payment(
                    ticket_id=ticket.id,
                    user_id=current_user.id,
                    amount=down_payment,
                    payment_method=payment_method or 'Cash',
                    paid_at=created_datetime
                )
                db.session.add(payment)
                
                payment_note = Note(
                    ticket_id=ticket.id,
                    user_id=current_user.id,
                    content=f"Initial down payment of {down_payment} received via {payment_method or 'Cash'}.",
                    is_internal=True
                )
                db.session.add(payment_note)

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating ticket: {str(e)}', 'error')
            return redirect(url_for('ticket.new_ticket'))
        
        flash(f'Ticket {ticket_number} created successfully!', 'success')
        return redirect(url_for('main.dashboard'))
        
    return render_template('ticket_form.html', 
                           customers=customers, 
                           users=users, 
                           common_problems=common_problems,
                           now_date=now_date,
                           now_time=now_time)


# ==================== MISSING VIEW ROUTES (REPAIRING NAV LINKS) ====================
@customer_bp.route('/')
@login_required
def customers_list():
    """Route for the Customers link in base.html"""
    page = request.args.get('page', 1, type=int)
    customers = Customer.query.order_by(desc(Customer.created_at)).paginate(page=page, per_page=15)
    return render_template('customers.html', customers=customers)

@main_bp.route('/devices')
@login_required
def devices_list():
    """Route for the Devices link in base.html"""
    page = request.args.get('page', 1, type=int)
    devices = Device.query.order_by(desc(Device.created_at)).paginate(page=page, per_page=15)
    return render_template('devices.html', devices=devices)

@report_bp.route('/')
@login_required
@require_permission('view_reports')
def reports():
    """Route for the Reports link in base.html"""
    # Calculate Total Revenue (Gross)
    gross_revenue = db.session.query(func.sum(Payment.amount)).scalar() or 0.0
    
    # Calculate Total Hardware Cost
    hardware_cost = db.session.query(
        func.sum(SparePart.cost * InvoiceItem.quantity)
    ).join(InvoiceItem, SparePart.id == InvoiceItem.spare_part_id).scalar() or 0.0

    monthly_stats = {
        'total_tickets': Ticket.query.count(),
        'completed_tickets': Ticket.query.filter_by(current_phase='Already Taken').count(),
        'total_revenue': float(gross_revenue) - float(hardware_cost) # Shows Net Profit
    }
    # Fetch recent tickets for the report table
    recent_tickets = Ticket.query.order_by(desc(Ticket.created_at)).limit(5).all()
    return render_template('reports.html', monthly_stats=monthly_stats, recent_tickets=recent_tickets)

@report_bp.route('/finance')
@login_required
@require_permission('view_reports')
def finance_report():
    """Detailed financial report showing Net Profit and Payment History"""
    # Total money paid by customers
    total_revenue = db.session.query(func.sum(Payment.amount)).scalar() or 0.0
    
    # Total wholesale cost of all hardware replacements used
    total_hardware_cost = db.session.query(
        func.sum(SparePart.cost * InvoiceItem.quantity)
    ).join(InvoiceItem, SparePart.id == InvoiceItem.spare_part_id).scalar() or 0.0
    
    net_profit = float(total_revenue) - float(total_hardware_cost)
    
    # Detailed payment history by customer
    payment_history = db.session.query(Payment, Ticket, Customer).join(
        Ticket, Payment.ticket_id == Ticket.id
    ).join(
        Customer, Ticket.customer_id == Customer.id
    ).order_by(desc(Payment.paid_at)).all()
    
    # Detailed material usage (Standard Parts + Manual Items)
    material_usage = db.session.query(InvoiceItem, Ticket, Customer).join(
        Invoice, InvoiceItem.invoice_id == Invoice.id
    ).join(
        Ticket, Invoice.ticket_id == Ticket.id
    ).join(
        Customer, Ticket.customer_id == Customer.id
    ).order_by(desc(InvoiceItem.id)).all()

    return render_template('finance_report.html', 
                           total_revenue=total_revenue,
                           total_hardware_cost=total_hardware_cost,
                           net_profit=net_profit,
                           payment_history=payment_history,
                           material_usage=material_usage)

@admin_bp.route('/', endpoint='dashboard')
@admin_bp.route('/dashboard', endpoint='dashboard')
@login_required
def admin_dashboard():
    """Admin control panel requested by base.html dropdown"""
    if not (current_user.is_superuser or current_user.has_role('manager')):
        flash('You do not have permission to access the admin panel.', 'error')
        return redirect(url_for('main.dashboard'))
    return render_template('admin/dashboard.html')

@admin_bp.route('/services', endpoint='manage_services')
@login_required
@require_permission('manage_services')
def manage_services():
    """Manage repair services and pricing"""
    services = Service.query.all()
    return render_template('admin/manage_services.html', services=services)

@admin_bp.route('/parts', endpoint='manage_parts')
@login_required
@require_permission('manage_services')
def manage_parts():
    """Manage spare parts inventory and pricing"""
    parts = SparePart.query.all()
    return render_template('admin/manage_parts.html', parts=parts)

@admin_bp.route('/parts/add', methods=['POST'], endpoint='add_part_admin')
@login_required
@require_permission('manage_services')
def add_part_admin():
    """Add a new spare part to inventory catalog"""
    name = request.form.get('name')
    description = request.form.get('description')
    cost = request.form.get('cost', type=float)
    selling_price = request.form.get('selling_price', type=float)
    stock = request.form.get('stock_quantity', 0, type=int)
    
    if not name or selling_price is None:
        flash('Part name and selling price are required.', 'error')
    else:
        part = SparePart(name=name, description=description, cost=cost or 0.0, 
                         selling_price=selling_price, stock_quantity=stock)
        db.session.add(part)
        db.session.commit()
        flash(f'Spare part "{name}" added to inventory.', 'success')
    return redirect(url_for('admin.manage_parts'))

@admin_bp.route('/parts/edit/<int:part_id>', methods=['POST'], endpoint='edit_part_admin')
@login_required
@require_permission('manage_services')
def edit_part_admin(part_id):
    """Update existing spare part details and global pricing"""
    part = db.session.get(SparePart, part_id)
    if not part:
        flash('Part not found.', 'error')
        return redirect(url_for('admin.manage_parts'))
        
    part.name = request.form.get('name')
    part.description = request.form.get('description')
    part.cost = request.form.get('cost', type=float)
    part.selling_price = request.form.get('selling_price', type=float)
    part.stock_quantity = request.form.get('stock_quantity', type=int)
    part.is_active = 'is_active' in request.form
    
    db.session.commit()
    flash(f'Part "{part.name}" updated.', 'success')
    return redirect(url_for('admin.manage_parts'))

@admin_bp.route('/parts/delete/<int:part_id>', methods=['POST'], endpoint='delete_part_admin')
@login_required
@require_permission('manage_services')
def delete_part_admin(part_id):
    """Permanently remove a spare part from the inventory catalog"""
    part = db.session.get(SparePart, part_id)
    if part:
        try:
            db.session.delete(part)
            db.session.commit()
            flash(f'Spare part "{part.name}" deleted successfully.', 'success')
        except Exception:
            db.session.rollback()
            flash('Cannot delete part because it is linked to existing invoices. Try deactivating it instead.', 'error')
    return redirect(url_for('admin.manage_parts'))

@admin_bp.route('/services/add', methods=['POST'], endpoint='add_service_admin')
@login_required
@require_permission('manage_services')
def add_service_admin():
    """Create a new repair service type"""
    name = request.form.get('name')
    description = request.form.get('description')
    price = request.form.get('price', type=float)
    
    if not name or price is None:
        flash('Service name and price are required.', 'error')
    else:
        service = Service(name=name, description=description, price=price)
        db.session.add(service)
        db.session.commit()
        flash(f'Service "{name}" created successfully.', 'success')
    
    return redirect(url_for('admin.manage_services'))

@admin_bp.route('/services/edit/<int:service_id>', methods=['POST'], endpoint='edit_service_admin')
@login_required
@require_permission('manage_services')
def edit_service_admin(service_id):
    """Update existing repair service details and pricing"""
    service = db.session.get(Service, service_id)
    if not service:
        flash('Service not found.', 'error')
        return redirect(url_for('admin.manage_services'))
        
    service.name = request.form.get('name')
    service.description = request.form.get('description')
    service.price = request.form.get('price', type=float)
    service.is_active = 'is_active' in request.form
    
    db.session.commit()
    flash(f'Service "{service.name}" updated.', 'success')
    return redirect(url_for('admin.manage_services'))

@admin_bp.route('/services/delete/<int:service_id>', methods=['POST'], endpoint='delete_service_admin')
@login_required
@require_permission('manage_services')
def delete_service_admin(service_id):
    """Permanently remove a service type from the catalog"""
    service = db.session.get(Service, service_id)
    if service:
        try:
            db.session.delete(service)
            db.session.commit()
            flash(f'Service "{service.name}" deleted successfully.', 'success')
        except Exception:
            db.session.rollback()
            flash('Cannot delete service because it is linked to existing repairs. Try deactivating it instead.', 'error')
    return redirect(url_for('admin.manage_services'))

@admin_bp.route('/users', endpoint='manage_users')
@login_required
@require_superuser()
def manage_users():
    users = User.query.paginate(page=request.args.get('page', 1, type=int), per_page=15)
    return render_template('admin/manage_users.html', users=users)

@admin_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@require_superuser()
def create_user():
    roles = Role.query.all()
    if request.method == 'POST':
        username = request.form.get('username')
        full_name = request.form.get('full_name')
        email = request.form.get('email')
        password = request.form.get('password')
        role_ids = request.form.getlist('roles')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
        else:
            user = User(username=username, full_name=full_name, email=email, is_active=True)
            user.set_password(password)
            for rid in role_ids:
                role = db.session.get(Role, int(rid))
                if role: user.roles.append(role)
            db.session.add(user)
            db.session.commit()
            flash('User created successfully!', 'success')
            return redirect(url_for('admin.manage_users'))
    return render_template('admin/create_user.html', roles=roles)

@admin_bp.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@require_superuser()
def edit_user(user_id):
    user = db.session.get(User, user_id)
    if not user: return redirect(url_for('admin.manage_users'))
    
    # Group permissions by category for the template grid
    permissions = Permission.query.all()
    permissions_by_category = {}
    for p in permissions:
        permissions_by_category.setdefault(p.category, []).append(p)

    roles = Role.query.all()
    if request.method == 'POST':
        user.full_name = request.form.get('full_name')
        user.email = request.form.get('email')
        user.is_active = 'is_active' in request.form
        
        # Handle password reset by superuser
        new_password = request.form.get('password')
        if new_password:
            if len(new_password) < 6:
                flash('New password must be at least 6 characters', 'error')
                return render_template('admin/edit_user.html', user=user, roles=roles, permissions_by_category=permissions_by_category)
            user.set_password(new_password)
            flash(f"Password for {user.username} has been updated.", "info")

        user.roles = []
        for rid in request.form.getlist('roles'):
            role = db.session.get(Role, int(rid))
            if role: user.roles.append(role)
            
        user.permissions = []
        for pid in request.form.getlist('permissions'):
            perm = db.session.get(Permission, int(pid))
            if perm: user.permissions.append(perm)

        db.session.commit()
        flash('User updated!', 'success')
        return redirect(url_for('admin.manage_users'))
    return render_template('admin/edit_user.html', user=user, roles=roles, permissions_by_category=permissions_by_category)

@admin_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
@require_superuser()
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if user and not user.is_superuser:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted.', 'success')
    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/problems', methods=['GET', 'POST'])
@login_required
@require_superuser()
def manage_problems():
    if request.method == 'POST':
        text = request.form.get('problem_text')
        if text and not CommonProblem.query.filter_by(problem_text=text).first():
            db.session.add(CommonProblem(problem_text=text))
            db.session.commit()
            flash('Common problem added!', 'success')
        return redirect(url_for('admin.manage_problems'))
    problems = CommonProblem.query.all()
    return render_template('admin/manage_common_problems.html', problems=problems)

@admin_bp.route('/problems/delete/<int:problem_id>', methods=['POST'])
@login_required
@require_superuser()
def delete_problem(problem_id):
    """Remove a common problem from the quick-select list"""
    problem = db.session.get(CommonProblem, problem_id)
    if problem:
        db.session.delete(problem)
        db.session.commit()
        flash('Common problem deleted.', 'success')
    return redirect(url_for('admin.manage_problems'))

@admin_bp.route('/backup', methods=['GET', 'POST'])
@login_required
@require_superuser()
def backup():
    if request.method == 'POST':
        backup_type = request.form.get('backup_type')
        if backup_type == 'json_data':
            data = {
                'customers': [{
                    'id': c.id, 'name': c.name, 'phone': c.phone, 'address': c.address, 
                    'created_at': c.created_at.isoformat() if c.created_at else None
                } for c in Customer.query.all()],
                'devices': [{
                    'id': d.id, 'customer_id': d.customer_id, 'device_type': d.device_type, 
                    'brand': d.brand, 'model_number': d.model_number, 'serial_number': d.serial_number,
                    'cpu': d.cpu, 'ram': d.ram, 'storage_type': d.storage_type, 
                    'storage_capacity': d.storage_capacity, 'color': d.color, 'notes': d.notes,
                    'created_at': d.created_at.isoformat() if d.created_at else None
                } for d in Device.query.all()],
                'tickets': [{
                    'id': t.id, 'ticket_number': t.ticket_number, 'customer_id': t.customer_id, 
                    'device_id': t.device_id, 'assigned_to': t.assigned_to, 
                    'problem_description': t.problem_description, 'items_included': t.items_included,
                    'current_phase': t.current_phase, 'estimated_cost': str(t.estimated_cost),
                    'actual_cost': str(t.actual_cost), 'device_picked_up': t.device_picked_up,
                    'picked_up_date': t.picked_up_date.isoformat() if t.picked_up_date else None,
                    'created_at': t.created_at.isoformat() if t.created_at else None
                } for t in Ticket.query.all()]
            }
            output = io.BytesIO(json.dumps(data, indent=4, default=str).encode('utf-8')) # default=str handles datetime objects
            return send_file(output, mimetype='application/json', as_attachment=True, 
                             download_name=f"logical_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json")
        elif backup_type == 'full_db':
            db_path = db.engine.url.database # Get the path to the SQLite DB file
            if os.path.exists(db_path):
                return send_file(db_path, mimetype='application/octet-stream', as_attachment=True,
                                 download_name=f"full_db_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.db")
            else:
                flash('Database file not found.', 'error')
                return redirect(url_for('admin.backup'))
    return render_template('admin/backup.html')

@admin_bp.route('/restore', methods=['POST'])
@login_required
@require_superuser()
def restore():
    """Restore database from an uploaded .db or .json file"""
    if 'backup_file' not in request.files:
        flash('No file selected', 'error')
        return redirect(url_for('admin.backup'))
    
    file = request.files['backup_file']
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(url_for('admin.backup'))

    if file and file.filename.lower().endswith('.db'):
        try:
            db_path = db.engine.url.database
            # Close connections to allow file overwrite
            db.session.remove()
            db.engine.dispose()
            
            # Overwrite the database file
            file.save(db_path)
            
            flash('System restored successfully from .db file. Please log in again.', 'success')
            logout_user()
            return redirect(url_for('auth.login'))
        except Exception as e:
            flash(f'Error restoring database: {str(e)}', 'error')
            
    elif file and file.filename.lower().endswith('.json'):
        try:
            # Logical restore (Append missing records)
            data = json.load(file)
            count = 0
            for c_data in data.get('customers', []):
                if not Customer.query.filter_by(phone=c_data['phone']).first():
                    new_customer = Customer(name=c_data['name'], phone=c_data['phone'], address=c_data.get('address'))
                    db.session.add(new_customer)
                    count += 1
            db.session.commit()
            flash(f'Import completed. Added {count} new customers from JSON.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error importing JSON data: {str(e)}', 'error')
    else:
        flash('Invalid file format. Please upload a .db or .json file.', 'error')
        
    return redirect(url_for('admin.backup'))

@ticket_bp.route('/view/<int:ticket_id>')
@login_required
@require_permission('view_ticket')
def ticket_detail(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash('Ticket not found', 'error')
        return redirect(url_for('main.dashboard'))
    
    # FIXED: Added context for services and spare parts management
    services = Service.query.filter_by(is_active=True).all()
    spare_parts = SparePart.query.filter_by(is_active=True).all()
    
    return render_template('ticket_detail.html', 
                           ticket=ticket, 
                           services=services, 
                           spare_parts=spare_parts)

@ticket_bp.route('/add_service/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('add_service')
def add_service(ticket_id):
    """Attach a standardized service to the ticket"""
    ticket = db.session.get(Ticket, ticket_id)
    if ticket and ticket.current_phase == 'Already Taken' and not (current_user.is_superuser or current_user.has_role('manager')):
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

    service_id = request.form.get('service_id')
    quantity = request.form.get('quantity', 1, type=int)
    
    service = db.session.get(Service, service_id)
    if service:
        ts = TicketService(
            ticket_id=ticket_id,
            service_id=service_id,
            quantity=quantity,
            price_charged=service.price
        )
        db.session.add(ts)
        db.session.commit()
        flash(f'Service "{service.name}" added.', 'success')
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

@ticket_bp.route('/remove_service/<int:ticket_id>/<int:ts_id>', methods=['POST'])
@login_required
@require_permission('add_service')
def remove_service(ticket_id, ts_id):
    """Remove a service entry from the ticket"""
    ticket = db.session.get(Ticket, ticket_id)
    if ticket and ticket.current_phase == 'Already Taken' and not (current_user.is_superuser or current_user.has_role('manager')):
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

    ts = db.session.get(TicketService, ts_id)
    if ts:
        db.session.delete(ts)
        db.session.commit()
        flash('Service removed.', 'success')
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

@ticket_bp.route('/add_part/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('add_service')
def add_part(ticket_id):
    """Record a spare part replacement (manages draft invoice automatically)"""
    ticket = db.session.get(Ticket, ticket_id)
    if ticket and ticket.current_phase == 'Already Taken' and not (current_user.is_superuser or current_user.has_role('manager')):
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

    part_id = request.form.get('part_id')
    manual_name = request.form.get('manual_name')
    quantity = request.form.get('quantity', 1, type=int)
    price = request.form.get('price', type=float)
    
    description = ""
    item_price = 0.0
    spare_part_id = None

    if part_id:
        part = db.session.get(SparePart, part_id)
        if part:
            description = part.name
            item_price = Decimal(str(price)) if price is not None else part.selling_price
            spare_part_id = part.id
    elif manual_name:
        description = manual_name
        if price is None:
            flash('Price is required for manual parts.', 'error')
            return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))
        item_price = Decimal(str(price))

    if description:
        # Ensure a draft invoice exists to hold the part costs
        invoice = Invoice.query.filter_by(ticket_id=ticket_id).first()
        if not invoice:
            invoice = Invoice(
                invoice_number=f"INV-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
                ticket_id=ticket_id,
                status='Draft'
            )
            db.session.add(invoice)
            db.session.flush()

        item = InvoiceItem(
            invoice_id=invoice.id,
            spare_part_id=spare_part_id,
            description=description,
            quantity=quantity,
            unit_price=item_price,
            total_price=item_price * quantity
        )
        db.session.add(item)
        invoice.calculate_total()
        db.session.commit()
        flash(f'Part "{description}" added to costs.', 'success')
    else:
        flash('Please select a part or enter a description.', 'error')
        
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

@ticket_bp.route('/remove_part/<int:ticket_id>/<int:item_id>', methods=['POST'])
@login_required
@require_permission('add_service')
def remove_part(ticket_id, item_id):
    """Remove a spare part from the ticket and recalculate invoice total"""
    ticket = db.session.get(Ticket, ticket_id)
    if ticket and ticket.current_phase == 'Already Taken' and not (current_user.is_superuser or current_user.has_role('manager')):
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

    item = db.session.get(InvoiceItem, item_id)
    if item:
        invoice = item.invoice
        db.session.delete(item)
        db.session.flush() # Ensure item is removed before recalculation
        invoice.calculate_total()
        db.session.commit()
        flash('Spare part removed.', 'success')
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

@ticket_bp.route('/record_payment/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('record_payment')
def record_payment(ticket_id):
    """Route to record manual payments against a ticket"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash('Ticket not found', 'error')
        return redirect(url_for('main.dashboard'))

    if ticket.current_phase == 'Already Taken' and not (current_user.is_superuser or current_user.has_role('manager')):
        flash('This ticket is locked and cannot be modified.', 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))

    amount = request.form.get('amount', type=float)
    method = request.form.get('payment_method', 'Cash')
    reference = request.form.get('reference', '')

    if amount is None or amount <= 0:
        flash('Please enter a valid payment amount.', 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))

    payment = Payment(
        ticket_id=ticket.id,
        user_id=current_user.id,
        amount=amount,
        payment_method=method,
        transaction_reference=reference,
        paid_at=datetime.now(timezone.utc)
    )
    db.session.add(payment)

    # Fetch global symbol for the automated note content
    shop_admin = User.query.filter_by(is_superuser=True).first()
    currency_map = {'USD': '$', 'IDR': 'Rp', 'EUR': '€', 'GBP': '£'}
    symbol = currency_map.get(shop_admin.currency, '$') if shop_admin else '$'

    # Create an automated note for the payment
    note = Note(
        ticket_id=ticket.id,
        user_id=current_user.id,
        note_type='Payment Received',
        content=f"Payment received: {symbol}{amount}. Method: {method}. Ref: {reference}",
        is_internal=True
    )
    db.session.add(note)

    db.session.commit()
    flash(f'Payment of {amount} recorded successfully.', 'success')
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))

@ticket_bp.route('/edit/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
@require_permission('edit_ticket')
def edit_ticket(ticket_id):
    """Route to edit basic ticket information"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash('Ticket not found', 'error')
        return redirect(url_for('main.dashboard'))

    if ticket.current_phase == 'Already Taken' and not (current_user.is_superuser or current_user.has_role('manager')):
        flash('This ticket is locked and cannot be modified.', 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))
        
    users = User.query.filter(User.roles.any(Role.name == 'technician')).all()
    
    if request.method == 'POST':
        ticket.items_included = request.form.get('items_included')
        ticket.problem_description = request.form.get('problem_description')
        assigned_to = request.form.get('assigned_to')
        
        # Update assignment safely
        ticket.assigned_to = int(assigned_to) if assigned_to else None
        
        db.session.commit()
        flash('Ticket updated successfully!', 'success')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))
        
    return render_template('edit_ticket.html', ticket=ticket, users=users)

@ticket_bp.route('/delete/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('delete_ticket')
def delete_ticket(ticket_id):
    """Permanently erase a ticket and its associated logs/notes"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash('Ticket not found', 'error')
        return redirect(url_for('main.dashboard'))
    
    db.session.delete(ticket)
    db.session.commit()
    flash(f'Ticket {ticket.ticket_number} has been permanently erased.', 'success')
    return redirect(url_for('main.dashboard'))

@ticket_bp.route('/update_phase/<int:ticket_id>', methods=['POST'])
@login_required
def update_phase(ticket_id):
    """Route to advance the repair ticket through its lifecycle"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash('Ticket not found', 'error')
        return redirect(url_for('main.dashboard'))

    if ticket.current_phase == 'Already Taken' and not (current_user.is_superuser or current_user.has_role('manager')):
        flash('This ticket is locked and cannot be modified.', 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))

    new_phase = request.form.get('new_phase')
    commentary = request.form.get('commentary', '')

    if not new_phase:
        flash('Please select a valid phase', 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))

    # Dynamic permission check based on target phase
    required_perm = 'update_phase'
    if new_phase == 'Fully Paid':
        required_perm = 'mark_as_paid'
    elif new_phase == 'Already Taken':
        required_perm = 'mark_as_taken'
        
    if not current_user.has_permission(required_perm):
        flash(f'You do not have the required permission ({required_perm}) to move a ticket to "{new_phase}".', 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))


    old_phase = ticket.current_phase
    ticket.current_phase = new_phase

    # Automatically set pickup flags if phase is "Already Taken"
    if new_phase == 'Already Taken':
        ticket.device_picked_up = True
        ticket.picked_up_date = datetime.now(timezone.utc)

    # Create audit log
    log = PhaseLog(
        ticket_id=ticket.id,
        user_id=current_user.id,
        old_phase=old_phase,
        new_phase=new_phase
    )
    db.session.add(log)

    # If commentary is provided, save it as a technical note
    if commentary:
        note = Note(
            ticket_id=ticket.id,
            user_id=current_user.id,
            note_type='Phase Update',
            content=f"Phase update to {new_phase}: {commentary}",
            is_internal=True
        )
        db.session.add(note)

    db.session.commit()
    flash(f'Ticket phase updated to {new_phase}', 'success')
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))

@customer_bp.route('/view/<int:customer_id>', endpoint='view_customer')
@login_required
@require_permission('view_customer')
def view_customer(customer_id):
    """Detailed view for a single customer and their devices"""
    customer = db.session.get(Customer, customer_id)
    if not customer:
        flash('Customer not found', 'error')
        return redirect(url_for('customer.customers_list'))
    return render_template('customer_detail.html', customer=customer)


@customer_bp.route('/new_customer', methods=['GET', 'POST'])
@login_required
@require_permission('create_customer')
def new_customer():
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        address = request.form.get('address', '')
        
        if not name or not phone:
            flash('Name and phone are required', 'error')
        else:
            customer = Customer(name=name, phone=phone, address=address)
            db.session.add(customer)
            db.session.commit()
            flash('Customer created successfully!', 'success')
            return redirect(url_for('customer.customers_list'))
    return render_template('new_customer.html')

@device_bp.route('/new_device', methods=['GET', 'POST'])
@login_required
@require_permission('create_device')
def new_device():
    customers = Customer.query.order_by(Customer.name).all()
    
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        device_type = request.form.get('device_type')
        brand = request.form.get('brand')
        
        if not all([customer_id, device_type, brand]):
            flash('Customer, Type, and Brand are required', 'error')
        else:
            device = Device(
                customer_id=customer_id,
                device_type=device_type,
                brand=brand,
                model_number=request.form.get('model_number'),
                cpu=request.form.get('cpu'),
                ram=request.form.get('ram'),
                storage_type=request.form.get('storage_type'),
                storage_capacity=request.form.get('storage_capacity'),
                color=request.form.get('color'),
                notes=request.form.get('notes')
            )
            db.session.add(device)
            db.session.commit()
            flash('Device added successfully!', 'success')
            return redirect(url_for('main.devices_list'))
            
    return render_template('new_device.html', customers=customers)

@device_bp.route('/edit/<int:device_id>', methods=['GET', 'POST'])
@login_required
@require_permission('edit_device')
def edit_device(device_id):
    """Route to edit hardware specifications for a specific device"""
    device = db.session.get(Device, device_id)
    if not device:
        flash('Device not found', 'error')
        return redirect(url_for('main.devices_list'))
    
    if request.method == 'POST':
        device.device_type = request.form.get('device_type')
        device.brand = request.form.get('brand')
        device.model_number = request.form.get('model_number')
        device.cpu = request.form.get('cpu')
        device.ram = request.form.get('ram')
        device.storage_type = request.form.get('storage_type')
        device.storage_capacity = request.form.get('storage_capacity')
        device.serial_number = request.form.get('serial_number')
        device.color = request.form.get('color')
        device.notes = request.form.get('notes')
        
        db.session.commit()
        flash('Device updated successfully!', 'success')
        return redirect(url_for('customer.view_customer', customer_id=device.customer_id))
        
    return render_template('edit_device.html', device=device)

@device_bp.route('/delete/<int:device_id>', methods=['POST'])
@login_required
@require_permission('delete_device')
def delete_device(device_id):
    device = db.session.get(Device, device_id)
    if device:
        customer_id = device.customer_id
        db.session.delete(device)
        db.session.commit()
        flash('Device deleted successfully.', 'success')
        return redirect(url_for('customer.view_customer', customer_id=customer_id))
    return redirect(url_for('main.devices_list'))

@ticket_bp.route('/download_invoice/<int:ticket_id>')
@login_required
@require_permission('create_invoice')
def download_invoice_pdf(ticket_id):
    """Placeholder for PDF generation logic (Future Feature)"""
    flash('PDF generation is currently being implemented. Please use the on-screen invoice view.', 'info')
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

@device_bp.route('/view/<int:device_id>')
@login_required
@require_permission('view_customer')
def device_detail(device_id):
    """Detailed view for a single device repair history"""
    device = db.session.get(Device, device_id)
    if not device:
        flash('Device not found', 'error')
        return redirect(url_for('main.dashboard'))
    return render_template('device_detail.html', device=device)

# ==================== CUSTOMER AJAX ROUTERS (COMPLETING MAIN.JS MATCH) ====================
@customer_bp.route('/search', methods=['GET'])
@login_required
def search_customers():
    """Asynchronous search endpoint requested by main.js customer_search input"""
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([])
        
    customers = Customer.query.filter(
        or_(Customer.name.ilike(f'%{query}%'), Customer.phone.ilike(f'%{query}%'))
    ).limit(10).all()
    
    return jsonify([{'id': c.id, 'name': c.name, 'phone': c.phone} for c in customers])


@customer_bp.route('/new', methods=['POST'])
@login_required
@require_permission('create_customer')
def new_customer_ajax():
    """Asynchronous modal form target managed by saveCustomerBtn click event"""
    name = request.form.get('name')
    phone = request.form.get('phone')
    address = request.form.get('address', '')
    
    if not name or not phone:
        return jsonify({'error': 'Name and phone fields are required'}), 400
        
    customer = Customer(name=name, phone=phone, address=address)
    db.session.add(customer)
    db.session.commit()
    
    return jsonify({'id': customer.id, 'name': customer.name})


# ==================== DEVICE AJAX ROUTERS (COMPLETING MAIN.JS MATCH) ====================
@device_bp.route('/search/<int:customer_id>', methods=['GET'])
@login_required
def search_devices(customer_id):
    """Asynchronous search endpoint checking customer context profiles"""
    query = request.args.get('q', '').strip()
    
    # Filter devices bound specifically to the active customer
    device_query = Device.query.filter_by(customer_id=customer_id)
    if query:
        device_query = device_query.filter(
            or_(Device.brand.ilike(f'%{query}%'), Device.model.ilike(f'%{query}%'), Device.device_type.ilike(f'%{query}%'))
        )
    devices = device_query.limit(10).all()

    return jsonify([{'id': d.id, 'display': d.display} for d in devices])


@device_bp.route('/new', methods=['POST'])
@login_required
@require_permission('create_device')
def new_device_ajax():
    """Asynchronous creation of devices via modal"""
    customer_id = request.form.get('customer_id')
    device_type = request.form.get('device_type')
    brand = request.form.get('brand')
    
    if not all([customer_id, device_type, brand]):
        return jsonify({'error': 'Customer, Type, and Brand are required'}), 400
        
    device = Device(
        customer_id=customer_id,
        device_type=device_type,
        brand=brand,
        model_number=request.form.get('model_number'),
        cpu=request.form.get('cpu'),
        ram=request.form.get('ram'),
        storage_type=request.form.get('storage_type'),
        storage_capacity=request.form.get('storage_capacity'),
        notes=request.form.get('notes')
    )
    db.session.add(device)
    db.session.commit()
    
    return jsonify({'id': device.id, 'display': device.display})
    
