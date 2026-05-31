from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user, login_user, logout_user
from werkzeug.security import generate_password_hash
from datetime import datetime
from sqlalchemy import desc
from models import db, User, Customer, Ticket, Note
import uuid

# Create blueprints
auth_bp = Blueprint('auth', __name__)
main_bp = Blueprint('main', __name__)
ticket_bp = Blueprint('ticket', __name__)
customer_bp = Blueprint('customer', __name__)


# ==================== AUTH ROUTES ====================
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        full_name = request.form.get('full_name')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('auth.register'))
        
        user = User(username=username, email=email, full_name=full_name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
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


# ==================== MAIN ROUTES ====================
@main_bp.route('/')
@main_bp.route('/dashboard')
@login_required
def dashboard():
    page = request.args.get('page', 1, type=int)
    status_filter = request.args.get('status', '')
    
    query = Ticket.query.order_by(desc(Ticket.created_at))
    
    if status_filter and status_filter in Ticket.STATUS_CHOICES:
        query = query.filter_by(status=status_filter)
    
    tickets = query.paginate(page=page, per_page=10)
    
    stats = {
        'total_tickets': Ticket.query.count(),
        'open_tickets': Ticket.query.filter_by(status='Open').count(),
        'in_progress': Ticket.query.filter_by(status='In Progress').count(),
        'completed': Ticket.query.filter_by(status='Completed').count(),
    }
    
    return render_template('dashboard.html', tickets=tickets, stats=stats, status_filter=status_filter)


# ==================== TICKET ROUTES ====================
@ticket_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_ticket():
    customers = Customer.query.all()
    users = User.query.filter_by(role='technician').all()
    
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        device_type = request.form.get('device_type')
        device_brand = request.form.get('device_brand')
        device_model = request.form.get('device_model')
        serial_number = request.form.get('serial_number')
        issue = request.form.get('issue_description')
        priority = request.form.get('priority', 'Medium')
        assigned_to = request.form.get('assigned_to')
        
        # Generate unique ticket number
        ticket_number = f"TKT-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        
        ticket = Ticket(
            ticket_number=ticket_number,
            customer_id=customer_id,
            device_type=device_type,
            device_brand=device_brand,
            device_model=device_model,
            serial_number=serial_number,
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
def view_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    return render_template('ticket_detail.html', ticket=ticket)


@ticket_bp.route('/<int:ticket_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    customers = Customer.query.all()
    users = User.query.filter_by(role='technician').all()
    
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
    
    return render_template('edit_ticket.html', ticket=ticket, customers=customers, users=users)


@ticket_bp.route('/<int:ticket_id>/note', methods=['POST'])
@login_required
def add_note(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    content = request.form.get('content')
    
    if content:
        note = Note(ticket_id=ticket_id, user_id=current_user.id, content=content)
        db.session.add(note)
        db.session.commit()
        flash('Note added successfully!', 'success')
    
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))


# ==================== CUSTOMER ROUTES ====================
@customer_bp.route('/')
@login_required
def customers_list():
    page = request.args.get('page', 1, type=int)
    customers = Customer.query.paginate(page=page, per_page=20)
    return render_template('customers.html', customers=customers)


@customer_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_customer():
    if request.method == 'POST':
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        address = request.form.get('address')
        city = request.form.get('city')
        zip_code = request.form.get('zip_code')
        
        customer = Customer(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            address=address,
            city=city,
            zip_code=zip_code
        )
        
        db.session.add(customer)
        db.session.commit()
        
        flash(f'Customer {customer.full_name} created successfully!', 'success')
        return redirect(url_for('customer.customers_list'))
    
    return render_template('new_customer.html')