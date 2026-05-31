from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user, login_user, logout_user
from datetime import datetime
from sqlalchemy import desc
from models import db, User, Role, Permission, Customer, Device, Ticket, Note, Payment
import uuid
from functools import wraps

# Create blueprints
auth_bp = Blueprint('auth', __name__)
main_bp = Blueprint('main', __name__)
ticket_bp = Blueprint('ticket', __name__)
customer_bp = Blueprint('customer', __name__)
admin_bp = Blueprint('admin', __name__)


# ==================== PERMISSION DECORATORS ====================
def require_permission(permission_name):
    """Decorator to check if user has specific permission"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Please log in first.', 'error')
                return redirect(url_for('auth.login'))
            if not current_user.has_permission(permission_name):
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
    """User profile - change username and password"""
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
        
        return redirect(url_for('auth.profile'))
    
    return render_template('profile.html')


# ==================== MAIN ROUTES ====================
@main_bp.route('/')
@main_bp.route('/dashboard')
@login_required
def dashboard():
    page = request.args.get('page', 1, type=int)
    
    query = Ticket.query.order_by(desc(Ticket.created_at))
    tickets = query.paginate(page=page, per_page=10)
    
    stats = {
        'total_tickets': Ticket.query.count(),
        'open_tickets': Ticket.query.filter_by(status='Open').count(),
        'in_progress': Ticket.query.filter_by(status='In Progress').count(),
        'completed': Ticket.query.filter_by(status='Completed').count(),
        'total_customers': Customer.query.count(),
    }
    
    return render_template('dashboard.html', tickets=tickets, stats=stats)


# ==================== TICKET ROUTES ====================
@ticket_bp.route('/new', methods=['GET', 'POST'])
@login_required
@require_permission('create_ticket')
def new_ticket():
    customers = Customer.query.all()
    users = User.query.filter(User.role.any(Role.name == 'technician')).all()
    
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        device_id = request.form.get('device_id')
        issue = request.form.get('issue_description')
        priority = request.form.get('priority', 'Medium')
        assigned_to = request.form.get('assigned_to')
        
        # Validate inputs
        if not device_id:
            flash('Please select a device', 'error')
            return redirect(url_for('ticket.new_ticket'))
        
        # Generate unique ticket number
        ticket_number = f"TKT-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        
        device = Device.query.get(device_id)
        
        ticket = Ticket(
            ticket_number=ticket_number,
            customer_id=customer_id,
            device_id=device_id,
            issue_description=issue,
            priority=priority,
            assigned_to=assigned_to if assigned_to else None
        )
        
        db.session.add(ticket)
        db.session.commit()
        
        flash(f'Ticket {ticket_number} created successfully!', 'success')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket.id))
    
    return render_template('new_ticket.html', customers=customers, users=users)


@ticket_bp.route('/<int:ticket_id>', methods=['GET'])
@login_required
@require_permission('view_ticket')
def view_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    return render_template('ticket_detail.html', ticket=ticket)


@ticket_bp.route('/<int:ticket_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('edit_ticket')
def edit_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    users = User.query.filter(User.role.any(Role.name == 'technician')).all()
    
    if request.method == 'POST':
        ticket.status = request.form.get('status')
        ticket.priority = request.form.get('priority')
        ticket.assigned_to = request.form.get('assigned_to') or None
        ticket.estimated_cost = request.form.get('estimated_cost') or None
        ticket.actual_cost = request.form.get('actual_cost') or None
        
        if ticket.status == 'Completed':
            ticket.completed_at = datetime.utcnow()
        
        db.session.commit()
        flash('Ticket updated successfully!', 'success')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket.id))
    
    return render_template('edit_ticket.html', ticket=ticket, users=users)


@ticket_bp.route('/<int:ticket_id>/note', methods=['POST'])
@login_required
@require_permission('add_note')
def add_note(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    content = request.form.get('content')
    note_type = request.form.get('note_type', 'General')
    
    if content:
        note = Note(
            ticket_id=ticket_id,
            user_id=current_user.id,
            note_type=note_type,
            content=content
        )
        db.session.add(note)
        
        # If it's a "Device Picked Up" note, update the ticket
        if note_type == 'Device Picked Up':
            ticket.device_picked_up = True
            ticket.picked_up_date = datetime.utcnow()
        
        db.session.commit()
        flash('Note added successfully!', 'success')
    
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))


@ticket_bp.route('/<int:ticket_id>/payment', methods=['POST'])
@login_required
@require_permission('record_payment')
def record_payment(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    amount = request.form.get('amount')
    payment_type = request.form.get('payment_type')
    payment_method = request.form.get('payment_method')
    notes = request.form.get('notes')
    
    if amount:
        payment = Payment(
            ticket_id=ticket_id,
            user_id=current_user.id,
            amount=float(amount),
            payment_type=payment_type,
            payment_method=payment_method,
            notes=notes
        )
        db.session.add(payment)
        
        # Add a payment note
        note = Note(
            ticket_id=ticket_id,
            user_id=current_user.id,
            note_type=payment_type,
            content=f'{payment_type}: {payment_method} - ${amount}'
        )
        db.session.add(note)
        db.session.commit()
        
        flash(f'Payment of ${amount} recorded successfully!', 'success')
    
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))


# ==================== CUSTOMER ROUTES ====================
@customer_bp.route('/')
@login_required
@require_permission('view_customer')
def customers_list():
    page = request.args.get('page', 1, type=int)
    customers = Customer.query.paginate(page=page, per_page=20)
    return render_template('customers.html', customers=customers)


@customer_bp.route('/new', methods=['GET', 'POST'])
@login_required
@require_permission('create_customer')
def new_customer():
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        address = request.form.get('address')
        
        customer = Customer(
            name=name,
            phone=phone,
            address=address
        )
        
        db.session.add(customer)
        db.session.commit()
        
        flash(f'Customer {customer.name} created successfully!', 'success')
        return redirect(url_for('customer.customers_list'))
    
    return render_template('new_customer.html')


@customer_bp.route('/<int:customer_id>', methods=['GET'])
@login_required
@require_permission('view_customer')
def view_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    return render_template('customer_detail.html', customer=customer)


@customer_bp.route('/<int:customer_id>/device/new', methods=['GET', 'POST'])
@login_required
@require_permission('create_device')
def add_device(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    
    if request.method == 'POST':
        device_type = request.form.get('device_type')
        brand = request.form.get('brand')
        model = request.form.get('model')
        serial_number = request.form.get('serial_number')
        color = request.form.get('color')
        notes = request.form.get('notes')
        
        device = Device(
            customer_id=customer_id,
            device_type=device_type,
            brand=brand,
            model=model,
            serial_number=serial_number,
            color=color,
            notes=notes
        )
        
        db.session.add(device)
        db.session.commit()
        
        flash(f'Device {brand} {model} added successfully!', 'success')
        return redirect(url_for('customer.view_customer', customer_id=customer_id))
    
    return render_template('add_device.html', customer=customer)


# ==================== ADMIN ROUTES ====================
@admin_bp.route('/dashboard')
@login_required
@require_superuser()
def admin_dashboard():
    users = User.query.all()
    roles = Role.query.all()
    permissions = Permission.query.all()
    
    stats = {
        'total_users': len(users),
        'total_roles': len(roles),
        'total_permissions': len(permissions),
    }
    
    return render_template('admin/dashboard.html', users=users, roles=roles, permissions=permissions, stats=stats)


@admin_bp.route('/users')
@login_required
@require_superuser()
def manage_users():
    page = request.args.get('page', 1, type=int)
    users = User.query.paginate(page=page, per_page=20)
    return render_template('admin/manage_users.html', users=users)


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@require_superuser()
def create_user():
    roles = Role.query.all()
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        full_name = request.form.get('full_name')
        password = request.form.get('password')
        role_ids = request.form.getlist('roles')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('admin.create_user'))
        
        user = User(
            username=username,
            email=email,
            full_name=full_name,
            is_active=True
        )
        user.set_password(password)
        
        # Assign roles
        for role_id in role_ids:
            role = Role.query.get(role_id)
            if role:
                user.role.append(role)
        
        db.session.add(user)
        db.session.commit()
        
        flash(f'User {username} created successfully!', 'success')
        return redirect(url_for('admin.manage_users'))
    
    return render_template('admin/create_user.html', roles=roles)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@require_superuser()
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    roles = Role.query.all()
    all_permissions = Permission.query.all()
    
    if request.method == 'POST':
        user.full_name = request.form.get('full_name')
        user.email = request.form.get('email')
        is_active = request.form.get('is_active')
        user.is_active = is_active == 'on'
        
        # Update roles
        role_ids = request.form.getlist('roles')
        user.role.clear()
        for role_id in role_ids:
            role = Role.query.get(role_id)
            if role:
                user.role.append(role)
        
        # Update permissions
        permission_ids = request.form.getlist('permissions')
        user.permissions.clear()
        for perm_id in permission_ids:
            perm = Permission.query.get(perm_id)
            if perm:
                user.permissions.append(perm)
        
        db.session.commit()
        flash('User updated successfully!', 'success')
        return redirect(url_for('admin.manage_users'))
    
    return render_template('admin/edit_user.html', user=user, roles=roles, all_permissions=all_permissions)


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@require_superuser()
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    
    if user.is_superuser:
        flash('Cannot delete superuser', 'error')
    else:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully!', 'success')
    
    return redirect(url_for('admin.manage_users'))


@admin_bp.route('/get-devices/<int:customer_id>')
@login_required
def get_customer_devices(customer_id):
    """API endpoint to get customer devices"""
    devices = Device.query.filter_by(customer_id=customer_id).all()
    return jsonify([{
        'id': d.id,
        'display': f"{d.brand} {d.model} ({d.device_type})"
    } for d in devices])