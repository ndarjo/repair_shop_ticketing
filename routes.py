from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user, login_user, logout_user
from werkzeug.utils import secure_filename
from datetime import datetime, timezone
from sqlalchemy import desc, or_, func
from sqlalchemy.orm import joinedload
from models import db, User, Role, Permission, Customer, Device, Ticket, Note, Payment, PhaseLog, Service, SparePart, Invoice, InvoiceItem, TicketService, CommonProblem, ShopSetting
import decimal
from decimal import Decimal
from app import limiter
from flask_babel import _
import hashlib
import uuid
from functools import wraps
import json
import io
import os
from cryptography.fernet import InvalidToken
import subprocess
import shutil

def safe_decimal(value, default='0.00'):
    """Helper to convert string to Decimal without crashing on invalid input"""
    try:
        if isinstance(value, Decimal):
            return value
        if value is None or str(value).strip() == '':
            return Decimal(default)
        return Decimal(str(value).replace(',', ''))
    except (ValueError, TypeError, decimal.InvalidOperation):
        return Decimal(default)

def get_logical_backup_data():
    """Helper to extract all critical system data for JSON backup"""
    return {
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
        } for t in Ticket.query.all()],
        'shop_settings': [{
            'shop_name': s.shop_name, 'shop_address': s.shop_address,
            'shop_phone': s.shop_phone, 'shop_email': s.shop_email,
            'logo_path': s.logo_path,
            'setup_completed': s.setup_completed
        } for s in ShopSetting.query.all()]
    }

# Create blueprints cleanly
auth_bp = Blueprint('auth', __name__)
main_bp = Blueprint('main', __name__)
ticket_bp = Blueprint('ticket', __name__)
customer_bp = Blueprint('customer', __name__)
admin_bp = Blueprint('admin', __name__)
report_bp = Blueprint('report', __name__)
device_bp = Blueprint('device', __name__)
onboarding_bp = Blueprint('onboarding', __name__)


# ==================== PERMISSION DECORATORS ====================
def require_permission(permission_name):
    """Decorator to check if user has specific permission"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                if request.mimetype == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': 'Authentication required'}), 401
                flash(_('Please log in first.'), 'error')
                return redirect(url_for('auth.login'))
            if not current_user.has_permission(permission_name):
                current_app.logger.warning(f"Access denied for user {current_user.username} to permission {permission_name}")
                if request.mimetype == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': 'Permission denied'}), 403
                flash(_('You do not have permission to access this page.'), 'error')
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
                flash(_('Please log in first.'), 'error')
                return redirect(url_for('auth.login'))
            if not current_user.is_superuser:
                flash(_('You do not have permission to access this page.'), 'error')
                return redirect(url_for('main.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==================== AUTH ROUTES ====================
@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    current_app.logger.debug(f"Login route accessed. Method: {request.method}, Mimetype: {request.mimetype}, Content-Type: {request.content_type}")

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash(_('Username and password are required'), 'error')
            return render_template('login.html')
        
        # PostgreSQL is case-sensitive; use func.lower to ensure case-insensitive login
        user = User.query.filter(func.lower(User.username) == func.lower(username)).first()
        
        if user:
            if user.check_password(password):
                if user.is_active:
                    login_user(user)
                    current_app.logger.info(f"User '{user.username}' logged in successfully.")
                    flash(_('Logged in successfully!'), 'success')
                    return redirect(url_for('main.dashboard'))
                else:
                    current_app.logger.warning(f"Login attempted for inactive user: '{username}'")
                    flash(_('Your account is deactivated. Please contact an administrator.'), 'error')
            else:
                current_app.logger.warning(f"Incorrect password for username: '{username}'")
                flash(_('Invalid username or password'), 'error')
        else:
            current_app.logger.warning(f"Failed login attempt for username: '{username}'")
            flash(_('Invalid username or password'), 'error')
    
    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash(_('You have been logged out.'), 'success')
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
                flash(_('Username already exists'), 'error')
            else:
                current_user.username = new_username
                db.session.commit()
                flash(_('Username changed successfully!'), 'success')
        
        elif action == 'change_password':
            old_password = request.form.get('old_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            if not current_user.check_password(old_password):
                flash(_('Current password is incorrect'), 'error')
            elif new_password != confirm_password:
                flash(_('New passwords do not match'), 'error')
            elif len(new_password) < 6:
                flash(_('Password must be at least 6 characters'), 'error')
            else:
                current_user.set_password(new_password)
                db.session.commit()
                flash(_('Password changed successfully!'), 'success')
        
        elif action == 'change_theme':
            theme = request.form.get('theme')
            color = request.form.get('color_theme')
            language = request.form.get('language')
            if theme in ['light', 'dark']:
                current_user.theme_preference = theme
            if color in ['blue', 'green', 'purple', 'red', 'orange']:
                current_user.color_theme = color
            if language in current_app.config['LANGUAGES']:
                current_user.language_preference = language

            # Restrict currency settings to superuser or manager
            if current_user.is_superuser or current_user.has_role('manager'):
                currency = request.form.get('currency')
                currency_decimals = request.form.get('currency_decimals', type=int)
                if currency in ['USD', 'IDR', 'EUR', 'GBP']:
                    current_user.currency = currency
                if currency_decimals is not None and 0 <= currency_decimals <= 4:
                    current_user.currency_decimals = currency_decimals

            db.session.commit()
            flash(_('Preferences updated successfully!'), 'success')
        
        return redirect(url_for('auth.profile'))
    
    return render_template('profile.html')


# ==================== ONBOARDING ROUTES ====================
@onboarding_bp.route('/setup', methods=['GET', 'POST'])
@login_required
def setup():
    """Initial system setup wizard for superusers"""
    if not current_user.is_superuser:
        flash(_('Only administrators can access the setup wizard.'), 'error')
        return redirect(url_for('main.dashboard'))
    
    settings = ShopSetting.query.first()
    if settings and settings.setup_completed:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        try:
            settings.shop_name = request.form.get('shop_name', 'Repair Shop')
            settings.shop_address = request.form.get('shop_address')
            settings.shop_phone = request.form.get('shop_phone')
            settings.shop_email = request.form.get('shop_email')
            
            currency = request.form.get('currency', 'USD')
            if currency in ['USD', 'IDR', 'EUR', 'GBP']:
                current_user.currency = currency
            
            language = request.form.get('language')
            if language in current_app.config['LANGUAGES']:
                current_user.language_preference = language
                
            settings.setup_completed = True
            db.session.commit()
            flash(_('Welcome! Your shop configuration is complete.'), 'success')
            return redirect(url_for('main.dashboard'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Onboarding setup failed: {str(e)}")
            flash(_('An error occurred during initial setup. Please try again.'), 'error')
            
    return render_template('onboarding.html', settings=settings)


# ==================== MAIN ROUTES ====================
@main_bp.route('/')
@main_bp.route('/dashboard')
@login_required
def dashboard():
    page = request.args.get('page', 1, type=int)
    
    # FIXED: Filter out tickets that have already been picked up by customers
    query = Ticket.query.options(
        joinedload(Ticket.customer), 
        joinedload(Ticket.device)
    ).filter(Ticket.current_phase != 'Already Taken', Ticket.is_archived == False).order_by(desc(Ticket.created_at))
    
    tickets = query.paginate(page=page, per_page=10)
    
    # Single aggregate query for status counts
    phase_counts = db.session.query(
        Ticket.current_phase, func.count(Ticket.id)
    ).group_by(Ticket.current_phase).all()
    phase_map = dict(phase_counts)

    stats = {
        'total_tickets': Ticket.query.filter(Ticket.current_phase != 'Already Taken', Ticket.is_archived == False).count(),
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
        query = Ticket.query.filter_by(current_phase='Already Taken', is_archived=False)
    else:
        # Show everything currently in the shop
        query = Ticket.query.options(
            joinedload(Ticket.customer), 
            joinedload(Ticket.device)
        ).filter(Ticket.current_phase != 'Already Taken', Ticket.is_archived == False)
        
    query = query.order_by(desc(Ticket.created_at))
    tickets = query.paginate(page=page, per_page=15)
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
        customer_id = request.form.get('customer_id', type=int)
        device_id = request.form.get('device_id', type=int)
        items_included = request.form.get('items_included', '')
        problem_description = request.form.get('problem_description', '')
        assigned_to = request.form.get('assigned_to', type=int)
        created_date = request.form.get('created_date')
        created_time = request.form.get('created_time')
        
        # Financial fields from form
        down_payment = safe_decimal(request.form.get('down_payment_amount'))
        payment_method = request.form.get('payment_method')
        
        if not device_id:
            flash(_('Please select a device'), 'error')
            return redirect(url_for('ticket.new_ticket'))
        
        # Verify device ownership to prevent data mismatch
        device = db.session.get(Device, device_id)
        if not device or str(device.customer_id) != str(customer_id):
            flash(_('Security Error: Selected device does not belong to the selected customer.'), 'error')
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
                    payment_method=payment_method or _('Cash'),
                    paid_at=created_datetime
                )
                db.session.add(payment)
                
                # Automated internal note for down payment
                payment_note = Note(
                    ticket_id=ticket.id,
                    user_id=current_user.id,
                    content=_('Initial down payment of %(amount)s received via %(method)s.', amount=down_payment, method=payment_method or _('Cash')),
                    is_internal=True
                )
                db.session.add(payment_note)

            db.session.commit()
            current_app.logger.info(f"New ticket created: {ticket_number} by user {current_user.username}")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating ticket: {str(e)}")
            flash(_('Error creating ticket: %(error)s', error=str(e)), 'error')
            return redirect(url_for('ticket.new_ticket'))
        
        # NAVIGATION POLISH: Redirect to detail page immediately so staff can add services/parts
        flash(_('Ticket %(ticket_num)s created successfully. You can now add services or parts.', ticket_num=ticket_number), 'success')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))
        
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
    try:
        return render_template('customers.html', customers=customers)
    except InvalidToken:
        flash(_('Security Error: Unable to decrypt customer data. Please check your ENCRYPTION_KEY.'), 'error')
        return redirect(url_for('main.dashboard'))

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
    selected_month = request.args.get('month') # Format: YYYY-MM

    # Calculate Total Revenue (Gross)
    rev_q = db.session.query(func.sum(Payment.amount)).join(
        Ticket, Payment.ticket_id == Ticket.id
    ).join(Customer, Ticket.customer_id == Customer.id)
    if selected_month:
        rev_q = rev_q.filter(func.to_char(Payment.paid_at, 'YYYY-MM') == selected_month)
    gross_revenue = rev_q.scalar() or Decimal('0.00')
    
    # Calculate Total Hardware Cost
    cost_q = db.session.query(
        func.sum(InvoiceItem.cost_price * InvoiceItem.quantity)
    )
    if selected_month:
        cost_q = cost_q.join(Invoice, InvoiceItem.invoice_id == Invoice.id).filter(
            func.to_char(Invoice.created_at, 'YYYY-MM') == selected_month
        )
    hardware_cost = cost_q.scalar() or Decimal('0.00')

    monthly_stats = {
        'total_tickets': Ticket.query.filter_by(is_archived=False).count(),
        'completed_tickets': Ticket.query.filter_by(current_phase='Already Taken', is_archived=False).count(),
        'gross_revenue': gross_revenue,
        'hardware_cost': hardware_cost,
        'net_profit': gross_revenue - hardware_cost,
        'selected_month': selected_month
    }

    # Get available months from payments and invoices for filtering
    months_p = db.session.query(func.to_char(Payment.paid_at, 'YYYY-MM')).distinct().all()
    months_i = db.session.query(func.to_char(Invoice.created_at, 'YYYY-MM')).distinct().all()
    available_months = sorted(list(set([m[0] for m in (months_p + months_i) if m[0]])), reverse=True)

    # Fetch recent tickets for the report table
    recent_tickets_q = Ticket.query
    if selected_month:
        recent_tickets_q = recent_tickets_q.filter(func.to_char(Ticket.created_at, 'YYYY-MM') == selected_month)
    recent_tickets = recent_tickets_q.order_by(desc(Ticket.created_at)).limit(5).all()

    return render_template('reports.html', 
                           monthly_stats=monthly_stats, 
                           recent_tickets=recent_tickets,
                           available_months=available_months)

@report_bp.route('/finance')
@login_required
@require_permission('view_reports')
def finance_report():
    """Detailed financial report showing Net Profit and Payment History"""
    selected_month = request.args.get('month') # Expecting YYYY-MM

    # Total money paid by customers
    rev_q = db.session.query(func.sum(Payment.amount)).join(
        Ticket, Payment.ticket_id == Ticket.id
    ).join(Customer, Ticket.customer_id == Customer.id)
    if selected_month:
        rev_q = rev_q.filter(func.to_char(Payment.paid_at, 'YYYY-MM') == selected_month)
    total_revenue = rev_q.scalar() or Decimal('0.00')
    
    # Total wholesale cost of all hardware replacements used
    cost_q = db.session.query(
        func.sum(InvoiceItem.cost_price * InvoiceItem.quantity)
    )
    if selected_month:
        cost_q = cost_q.join(Invoice, InvoiceItem.invoice_id == Invoice.id).filter(
            func.to_char(Invoice.created_at, 'YYYY-MM') == selected_month
        )
    total_hardware_cost = cost_q.scalar() or Decimal('0.00')
    
    net_profit = total_revenue - total_hardware_cost
    
    # Detailed payment history by customer
    ph_q = db.session.query(Payment, Ticket, Customer).join(
        Ticket, Payment.ticket_id == Ticket.id
    ).join(
        Customer, Ticket.customer_id == Customer.id
    )
    if selected_month:
        ph_q = ph_q.filter(func.to_char(Payment.paid_at, 'YYYY-MM') == selected_month)
    payment_history = ph_q.order_by(desc(Payment.paid_at)).all()
    
    # Detailed material usage (Standard Parts + Manual Items)
    mu_q = db.session.query(InvoiceItem, Ticket, Customer).join(
        Invoice, InvoiceItem.invoice_id == Invoice.id
    ).join(
        Ticket, Invoice.ticket_id == Ticket.id
    ).join(
        Customer, Ticket.customer_id == Customer.id
    )
    if selected_month:
        mu_q = mu_q.filter(func.to_char(Invoice.created_at, 'YYYY-MM') == selected_month)
    material_usage = mu_q.order_by(desc(InvoiceItem.id)).all()

    # Monthly breakdown for financial analysis
    monthly_data = {}
    
    # Aggregate Revenue by Month
    rev_results = db.session.query(
        func.to_char(Payment.paid_at, 'YYYY-MM').label('month'),
        func.sum(Payment.amount)
    ).join(Ticket, Payment.ticket_id == Ticket.id)\
     .join(Customer, Ticket.customer_id == Customer.id)\
     .group_by('month').all()

    for month, total in rev_results:
        if month:
            monthly_data[month] = {'revenue': Decimal(str(total)), 'costs': Decimal('0.00'), 'profit': Decimal(str(total))}

    # Aggregate Hardware Costs by Month (based on Invoice date)
    cost_results = db.session.query(
        func.to_char(Invoice.created_at, 'YYYY-MM').label('month'),
        func.sum(InvoiceItem.cost_price * InvoiceItem.quantity)
    ).join(Invoice, InvoiceItem.invoice_id == Invoice.id)\
     .group_by('month').all()

    for month, total in cost_results:
        if month:
            if month not in monthly_data:
                monthly_data[month] = {'revenue': Decimal('0.00'), 'costs': Decimal('0.00'), 'profit': Decimal('0.00')}
            monthly_data[month]['costs'] = Decimal(str(total))
            monthly_data[month]['profit'] = monthly_data[month]['revenue'] - monthly_data[month]['costs']

    # Sort months descending for the report
    monthly_analysis = sorted([{'month': k, **v} for k, v in monthly_data.items()], 
                              key=lambda x: x['month'], reverse=True)

    return render_template('finance_report.html', 
                           total_revenue=total_revenue,
                           total_hardware_cost=total_hardware_cost,
                           net_profit=net_profit,
                           payment_history=payment_history,
                           material_usage=material_usage,
                           monthly_analysis=monthly_analysis,
                           selected_month=selected_month,
                           available_months=[m['month'] for m in monthly_analysis])

@admin_bp.route('/', endpoint='dashboard')
@admin_bp.route('/dashboard', endpoint='dashboard')
@login_required
def admin_dashboard():
    """Admin control panel requested by base.html dropdown"""
    if not (current_user.is_superuser or current_user.has_role('manager')):
        flash(_('You do not have permission to access the admin panel.'), 'error')
        return redirect(url_for('main.dashboard'))
    return render_template('admin/dashboard.html')

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@require_superuser()
def shop_settings():
    """Configure shop name, location, contact and logo"""
    settings = ShopSetting.query.first()
    if not settings:
        settings = ShopSetting()
        db.session.add(settings)
        db.session.commit()
        
    if request.method == 'POST':
        settings.shop_name = request.form.get('shop_name', 'Repair Shop')
        settings.shop_address = request.form.get('shop_address')
        settings.shop_phone = request.form.get('shop_phone')
        settings.shop_email = request.form.get('shop_email')
        
        # Handle Logo Upload
        logo_file = request.files.get('shop_logo')
        if logo_file and logo_file.filename != '':
            filename = secure_filename(f"logo_{uuid.uuid4().hex[:8]}_{logo_file.filename}")
            upload_path = os.path.join(current_app.static_folder, 'uploads', 'logos')
            
            if not os.path.exists(upload_path):
                os.makedirs(upload_path)
                
            logo_file.save(os.path.join(upload_path, filename))
            settings.logo_path = filename
            
        db.session.commit()
        flash(_('Shop settings updated successfully.'), 'success')
        return redirect(url_for('admin.shop_settings'))
        
    return render_template('admin/settings.html', settings=settings)

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
    cost = Decimal(request.form.get('cost') or '0')
    selling_price = Decimal(request.form.get('selling_price') or '0')
    stock = request.form.get('stock_quantity', 0, type=int)
    
    if not name or selling_price is None:
        flash(_('Part name and selling price are required.'), 'error')
    else:
        part = SparePart(name=name, description=description, cost=cost or Decimal('0.00'), 
                         selling_price=selling_price, stock_quantity=stock)
        db.session.add(part)
        db.session.commit()
        flash(_('Spare part "%(name)s" added to inventory.', name=name), 'success')
    return redirect(url_for('admin.manage_parts'))

@admin_bp.route('/parts/edit/<int:part_id>', methods=['POST'], endpoint='edit_part_admin')
@login_required
@require_permission('manage_services')
def edit_part_admin(part_id):
    """Update existing spare part details and global pricing"""
    part = db.session.get(SparePart, part_id)
    if not part:
        flash(_('Part not found.'), 'error')
        return redirect(url_for('admin.manage_parts'))
        
    part.name = request.form.get('name')
    part.description = request.form.get('description')
    part.cost = Decimal(request.form.get('cost') or '0')
    part.selling_price = Decimal(request.form.get('selling_price') or '0')
    part.stock_quantity = request.form.get('stock_quantity', type=int)
    part.is_active = 'is_active' in request.form
    
    db.session.commit()
    flash(_('Part "%(name)s" updated.', name=part.name), 'success')
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
            flash(_('Spare part "%(name)s" deleted successfully.', name=part.name), 'success')
        except Exception:
            db.session.rollback()
            flash(_('Cannot delete part because it is linked to existing invoices. Try deactivating it instead.'), 'error')
    return redirect(url_for('admin.manage_parts'))

@admin_bp.route('/services/add', methods=['POST'], endpoint='add_service_admin')
@login_required
@require_permission('manage_services')
def add_service_admin():
    """Create a new repair service type"""
    name = request.form.get('name')
    description = request.form.get('description')
    price = Decimal(request.form.get('price') or '0')
    
    if not name or price is None:
        flash(_('Service name and price are required.'), 'error')
    else:
        service = Service(name=name, description=description, price=price)
        db.session.add(service)
        db.session.commit()
        flash(_('Service "%(name)s" created successfully.', name=name), 'success')
    
    return redirect(url_for('admin.manage_services'))

@admin_bp.route('/services/edit/<int:service_id>', methods=['POST'], endpoint='edit_service_admin')
@login_required
@require_permission('manage_services')
def edit_service_admin(service_id):
    """Update existing repair service details and pricing"""
    service = db.session.get(Service, service_id)
    if not service:
        flash(_('Service not found.'), 'error')
        return redirect(url_for('admin.manage_services'))
        
    service.name = request.form.get('name')
    service.description = request.form.get('description')
    service.price = Decimal(request.form.get('price') or '0')
    service.is_active = 'is_active' in request.form
    
    db.session.commit()
    flash(_('Service "%(name)s" updated.', name=service.name), 'success')
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
            flash(_('Service "%(name)s" deleted successfully.', name=service.name), 'success')
        except Exception:
            db.session.rollback()
            flash(_('Cannot delete service because it is linked to existing repairs. Try deactivating it instead.'), 'error')
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
            flash(_('Username already exists'), 'error')
        else:
            user = User(username=username, full_name=full_name, email=email, is_active=True)
            user.set_password(password)
            for rid in role_ids:
                role = db.session.get(Role, int(rid))
                if role: user.roles.append(role)
            db.session.add(user)
            db.session.commit()
            flash(_('User created successfully!'), 'success')
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
                flash(_('New password must be at least 6 characters'), 'error')
                return render_template('admin/edit_user.html', user=user, roles=roles, permissions_by_category=permissions_by_category)
            user.set_password(new_password)
            flash(_('Password for %(user)s has been updated.', user=user.username), "info")

        user.roles = []
        for rid in request.form.getlist('roles'):
            role = db.session.get(Role, int(rid))
            if role: user.roles.append(role)
            
        user.permissions = []
        for pid in request.form.getlist('permissions'):
            perm = db.session.get(Permission, int(pid))
            if perm: user.permissions.append(perm)

        db.session.commit()
        flash(_('User updated!'), 'success')
        return redirect(url_for('admin.manage_users'))
    return render_template('admin/edit_user.html', user=user, roles=roles, permissions_by_category=permissions_by_category)

@admin_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
@require_superuser()
def delete_user(user_id):
    """Permanently delete a user account if no audit dependencies exist"""
    user = db.session.get(User, user_id)
    if not user:
        flash(_('User not found.'), 'error')
        return redirect(url_for('admin.manage_users'))

    if user.is_superuser:
        flash(_('Cannot delete a superuser account.'), 'error')
        return redirect(url_for('admin.manage_users'))

    if user.id == current_user.id:
        flash(_('Security Error: You cannot delete your own account while logged in.'), 'error')
        return redirect(url_for('admin.manage_users'))

    try:
        db.session.delete(user)
        db.session.commit()
        flash(_('User account "%(user)s" deleted successfully.', user=user.username), 'success')
    except Exception:
        db.session.rollback()
        flash(_('Cannot delete "%(user)s" because they have recorded activity. Please deactivate them instead.', user=user.username), 'error')

    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/problems', methods=['GET', 'POST'])
@login_required
@require_superuser()
@limiter.limit("10 per minute") # Rate limit for adding/deleting problems
def manage_problems():
    if request.method == 'POST':
        text = request.form.get('problem_text')
        if text and not CommonProblem.query.filter_by(problem_text=text).first():
            db.session.add(CommonProblem(problem_text=text))
            db.session.commit()
            flash(_('Common problem added!'), 'success')
        return redirect(url_for('admin.manage_problems'))
    problems = CommonProblem.query.all()
    return render_template('admin/manage_common_problems.html', problems=problems)

@admin_bp.route('/problems/delete/<int:problem_id>', methods=['POST'])
@login_required
@require_superuser()
@limiter.limit("10 per minute") # Rate limit for adding/deleting problems
def delete_problem(problem_id):
    """Remove a common problem from the quick-select list"""
    problem = db.session.get(CommonProblem, problem_id)
    if problem:
        db.session.delete(problem)
        db.session.commit()
        flash(_('Common problem deleted.'), 'success')
    return redirect(url_for('admin.manage_problems'))

@admin_bp.route('/backup', methods=['GET', 'POST'])
@login_required
@require_superuser()
def backup():
    if request.method == 'POST':
        backup_type = request.form.get('backup_type')
        if backup_type == 'json_data':
            data = get_logical_backup_data()
            output = io.BytesIO(json.dumps(data, indent=4, default=str).encode('utf-8')) # default=str handles datetime objects
            return send_file(output, mimetype='application/json', as_attachment=True, 
                             download_name=f"logical_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json")
        elif backup_type == 'full_db':
            # Binary file backup only works for SQLite
            if 'sqlite' in db.engine.url.drivername:
                db_path = db.engine.url.database
                if os.path.exists(db_path):
                    return send_file(db_path, mimetype='application/octet-stream', as_attachment=True,
                                     download_name=f"full_db_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.db")
                flash(_('SQLite database file not found.'), 'error')
            elif 'postgresql' in db.engine.url.drivername:
                if not shutil.which('pg_dump'):
                    flash(_('The "pg_dump" utility was not found in the system path. Please install the PostgreSQL client tools (e.g., sudo apt install postgresql-client) to use this feature.'), 'error')
                    return redirect(url_for('admin.backup'))

                try:
                    url = db.engine.url
                    env = os.environ.copy()
                    if url.password:
                        env['PGPASSWORD'] = url.password
                    
                    cmd = [
                        'pg_dump',
                        '-h', url.host or 'localhost',
                        '-p', str(url.port or 5432),
                        '-U', url.username or 'postgres',
                        '-F', 'c', # Custom format (compressed binary)
                        url.database
                    ]
                    
                    result = subprocess.run(cmd, env=env, capture_output=True)
                    
                    if result.returncode != 0:
                        raise Exception(result.stderr.decode())
                        
                    output = io.BytesIO(result.stdout)
                    return send_file(output, mimetype='application/octet-stream', as_attachment=True, 
                                     download_name=f"pg_full_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.dump")
                except Exception as e:
                    current_app.logger.error(f"PostgreSQL backup failed: {str(e)}")
                    flash(_('Error creating PostgreSQL backup: %(error)s', error=str(e)), 'error')
            else:
                flash(_('Full binary backup is not supported for driver: %(driver)s', driver=db.engine.url.drivername), 'warning')
        return redirect(url_for('admin.backup'))
    return render_template('admin/backup.html')

@admin_bp.route('/restore', methods=['POST'])
@login_required
@require_superuser()
def restore():
    """Restore database from an uploaded .db, .dump or .json file"""
    if 'backup_file' not in request.files:
        flash(_('No file selected'), 'error')
        return redirect(url_for('admin.backup'))
    
    file = request.files['backup_file']
    if file.filename == '':
        flash(_('No file selected'), 'error')
        return redirect(url_for('admin.backup'))

    if file and file.filename.lower().endswith('.db'):
        if 'sqlite' in db.engine.url.drivername:
            try:
                db_path = db.engine.url.database
                # Close connections to allow file overwrite
                db.session.remove()
                db.engine.dispose()
                
                # Overwrite the database file
                file.save(db_path)
                
                current_app.logger.info(f"System restored from .db file by {current_user.username}")
                flash(_('System restored successfully from .db file. Please log in again.'), 'success')
                logout_user()
                return redirect(url_for('auth.login'))
            except Exception as e:
                current_app.logger.error(f"Database restore failed: {str(e)}")
                flash(_('Error restoring database: %(error)s', error=str(e)), 'error')
        else:
            flash(_('Binary .db restore is only supported for SQLite databases.'), 'error')
            
    elif file and file.filename.lower().endswith('.dump'):
        if 'postgresql' in db.engine.url.drivername:
            if not shutil.which('pg_restore'):
                flash(_('The "pg_restore" utility was not found in the system path. Please install the PostgreSQL client tools (e.g., sudo apt install postgresql-client) to use this feature.'), 'error')
                return redirect(url_for('admin.backup'))

            try:
                temp_path = os.path.join(current_app.config['BACKUP_DIR'], 'temp_restore.dump')
                file.save(temp_path)
                
                url = db.engine.url
                env = os.environ.copy()
                if url.password:
                    env['PGPASSWORD'] = url.password
                
                # IMPORTANT: Close active connections to prevent locks during schema modification
                db.session.remove()
                db.engine.dispose()

                # pg_restore -c (clean) drops objects before recreating them.
                # --if-exists prevents errors if the database is currently empty.
                # --no-owner and --no-privileges ensure compatibility across different DB users.
                cmd = [
                    'pg_restore',
                    '-h', url.host or 'localhost',
                    '-p', str(url.port or 5432),
                    '-U', url.username or 'postgres',
                    '-d', url.database,
                    '-c',
                    '--if-exists',
                    '--no-owner',
                    '--no-privileges',
                    temp_path
                ]
                
                result = subprocess.run(cmd, env=env, capture_output=True)
                if os.path.exists(temp_path): os.remove(temp_path)
                
                # Exit code 1 is often non-fatal warnings in pg_restore
                if result.returncode not in [0, 1]:
                    raise Exception(result.stderr.decode())

                current_app.logger.info(f"System restored from .dump file by {current_user.username}")
                flash(_('System restored successfully from PostgreSQL dump. Please log in again.'), 'success')
                logout_user()
                return redirect(url_for('auth.login'))
            except Exception as e:
                current_app.logger.error(f"PostgreSQL restore failed: {str(e)}")
                flash(_('Error restoring PostgreSQL dump: %(error)s', error=str(e)), 'error')
        else:
            flash(_('PostgreSQL .dump restore is only supported for PostgreSQL databases.'), 'error')
            
    elif file and file.filename.lower().endswith('.json'):
        try:
            # Logical restore (Append missing records)
            data = json.load(file)
            count = 0
            for c_data in data.get('customers', []):
                # PII Security: Use the blind index hash for duplicate check during restore
                p_hash = hashlib.sha256((current_app.config['BLIND_INDEX_SALT'] + c_data['phone']).encode()).hexdigest()
                if not Customer.query.filter_by(phone_hash=p_hash).first():
                    new_customer = Customer(name=c_data['name'], phone=c_data['phone'], address=c_data.get('address'))
                    db.session.add(new_customer)
                    count += 1
            db.session.commit()
            current_app.logger.info(f"Imported {count} customers from JSON by {current_user.username}")
            flash(_('Import completed. Added %(count)s new customers from JSON.', count=count), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"JSON import failed: {str(e)}")
            flash(_('Error importing JSON data: %(error)s', error=str(e)), 'error')
    else:
        flash(_('Invalid file format. Please upload a .db, .dump or .json file.'), 'error')
        
    return redirect(url_for('admin.backup'))

@ticket_bp.route('/view/<int:ticket_id>')
@login_required
@require_permission('view_ticket')
def ticket_detail(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash(_('Ticket not found'), 'error')
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
    if ticket and ticket.current_phase == 'Already Taken':
        flash(_('This ticket is locked and cannot be modified.'), 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

    # Ensure a draft invoice exists to hold the charges
    invoice = Invoice.query.filter_by(ticket_id=ticket_id).first()
    if not invoice:
        invoice = Invoice(
            invoice_number=f"INV-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
            ticket_id=ticket_id,
            status='Draft'
        )
        db.session.add(invoice)
        db.session.flush()

    service_id = request.form.get('service_id')
    quantity = request.form.get('quantity', 1, type=int)
    
    service = db.session.get(Service, service_id)
    if service:
        try:
            ts = TicketService(
                ticket_id=ticket_id,
                service_id=service_id,
                quantity=quantity,
                price_charged=service.price
            )
            db.session.add(ts)
            db.session.flush()
            invoice.calculate_total()
            db.session.commit()
            flash(_('Service "%(name)s" added.', name=service.name), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to add service to ticket {ticket_id}: {str(e)}")
            flash(_('Database error: Service could not be added.'), 'error')
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

@ticket_bp.route('/remove_service/<int:ticket_id>/<int:ts_id>', methods=['POST'])
@login_required
@require_permission('add_service')
def remove_service(ticket_id, ts_id):
    """Remove a service entry from the ticket"""
    ticket = db.session.get(Ticket, ticket_id)
    if ticket and ticket.current_phase == 'Already Taken':
        flash(_('This ticket is locked and cannot be modified.'), 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

    ts = db.session.get(TicketService, ts_id)
    if ts:
        invoice = Invoice.query.filter_by(ticket_id=ticket_id).first()
        db.session.delete(ts)
        db.session.flush()
        if invoice:
            invoice.calculate_total()
        db.session.commit()
        flash(_('Service removed.'), 'success')
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

@ticket_bp.route('/add_part/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('add_service')
def add_part(ticket_id):
    """Record a spare part replacement (manages draft invoice automatically)"""
    ticket = db.session.get(Ticket, ticket_id)
    if ticket and ticket.current_phase == 'Already Taken':
        flash(_('This ticket is locked and cannot be modified.'), 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

    part_id = request.form.get('part_id')
    manual_name = request.form.get('manual_name')
    quantity = request.form.get('quantity', 1, type=int)
    price_val = request.form.get('price', '').strip()
    cost_val = request.form.get('cost', '').strip()
    
    description = ""
    item_price = Decimal('0.00')
    item_cost = Decimal('0.00')
    spare_part_id = None

    try:
        if part_id:
            part = db.session.get(SparePart, part_id)
            if part:
                description = part.name
                # Use manually entered price if provided; otherwise fallback to catalog price
                item_price = Decimal(price_val) if price_val else part.selling_price
                item_cost = part.cost
                spare_part_id = part.id
        elif manual_name:
            description = manual_name
            if not price_val:
                flash(_('Price is required for manual parts.'), 'error')
                return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))
            item_price = Decimal(price_val)
            # Use manually entered wholesale cost if provided
            if cost_val:
                item_cost = Decimal(cost_val)
    except Exception:
        flash(_('Invalid price format entered. Please use numbers only.'), 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

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

        try:
            item = InvoiceItem(
                invoice_id=invoice.id,
                spare_part_id=spare_part_id,
                description=description,
                quantity=quantity,
                cost_price=item_cost,
                unit_price=item_price,
                total_price=item_price * quantity
            )
            db.session.add(item)
            invoice.calculate_total()
            db.session.commit()
            flash(_('Part "%(name)s" added to costs.', name=description), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Failed to add part to ticket {ticket_id}: {str(e)}")
            flash(_('Database error: Part could not be recorded.'), 'error')
    else:
        flash(_('Please select a part or enter a description.'), 'error')
        
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

@ticket_bp.route('/remove_part/<int:ticket_id>/<int:item_id>', methods=['POST'])
@login_required
@require_permission('add_service')
def remove_part(ticket_id, item_id):
    """Remove a spare part from the ticket and recalculate invoice total"""
    ticket = db.session.get(Ticket, ticket_id)
    if ticket and ticket.current_phase == 'Already Taken':
        flash(_('This ticket is locked and cannot be modified.'), 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

    item = db.session.get(InvoiceItem, item_id)
    if item:
        invoice = item.invoice
        db.session.delete(item)
        db.session.flush() # Ensure item is removed before recalculation
        invoice.calculate_total()
        db.session.commit()
        flash(_('Spare part removed.'), 'success')
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

@ticket_bp.route('/create_invoice/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('create_invoice')
def create_invoice(ticket_id):
    """Finalize the draft invoice or create a new one for the ticket"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash(_('Ticket not found'), 'error')
        return redirect(url_for('main.dashboard'))

    invoice = Invoice.query.filter_by(ticket_id=ticket_id).first()
    
    if not invoice:
        invoice = Invoice(
            invoice_number=f"INV-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
            ticket_id=ticket_id,
            status='Unpaid'
        )
        db.session.add(invoice)
    else:
        if invoice.status == 'Draft':
            invoice.status = 'Unpaid'
    
    invoice.calculate_total()
    db.session.commit()
    flash(_('Invoice %(num)s created successfully.', num=invoice.invoice_number), 'success')
    return redirect(url_for('ticket.view_invoice', invoice_id=invoice.id))

@ticket_bp.route('/invoice/<int:invoice_id>')
@login_required
@require_permission('view_ticket')
def view_invoice(invoice_id):
    """View the generated invoice details"""
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        flash(_('Invoice not found'), 'error')
        return redirect(url_for('main.dashboard'))
    return render_template('invoice.html', invoice=invoice)

@ticket_bp.route('/record_payment/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('record_payment')
def record_payment(ticket_id):
    """Route to record manual payments against a ticket"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash(_('Ticket not found'), 'error')
        return redirect(url_for('main.dashboard'))

    if ticket.current_phase == 'Already Taken':
        flash(_('This ticket is locked and cannot be modified.'), 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))

    amount = safe_decimal(request.form.get('amount'))
    method = request.form.get('payment_method', _('Cash'))
    reference = request.form.get('reference', '')

    if amount == 0:
        flash(_('Please enter a valid non-zero payment amount.'), 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))

    try:
        payment = Payment(
            ticket_id=ticket.id,
            user_id=current_user.id,
            amount=amount,
            payment_method=method,
            transaction_reference=reference,
            paid_at=datetime.now(timezone.utc)
        )
        db.session.add(payment)
        db.session.flush()

        # Synchronize Invoice status with the new payment balance
        invoice = Invoice.query.filter_by(ticket_id=ticket.id).first()
        if invoice:
            balance = invoice.remaining_balance
            if balance <= 0:
                invoice.status = 'Paid'
            elif balance < invoice.total_amount:
                invoice.status = 'Partial'

        # Fetch global symbol for the automated note content
        shop_admin = User.query.filter_by(is_superuser=True).first()
        currency_map = {'USD': '$', 'IDR': 'Rp', 'EUR': '€', 'GBP': '£'}
        symbol = currency_map.get(shop_admin.currency, '$') if shop_admin else '$'

        # Create an automated note for the payment
        note_type = _('Payment Received') if amount > 0 else _('Change Given / Refund')
        note_content = _('%(type)s: %(symbol)s%(amount)s. Method: %(method)s. Ref: %(ref)s', type=note_type, symbol=symbol, amount=abs(amount), method=method, ref=reference)

        note = Note(
            ticket_id=ticket.id,
            user_id=current_user.id,
            note_type=note_type,
            content=note_content,
            is_internal=True
        )
        db.session.add(note)

        db.session.commit()
        flash(_('Payment of %(amount)s recorded successfully.', amount=amount), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Critical: Payment recording failed for ticket {ticket_id}: {str(e)}")
        flash(_('Critical Error: Could not save payment details.'), 'error')
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))

@ticket_bp.route('/edit/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
@require_permission('edit_ticket')
def edit_ticket(ticket_id):
    """Route to edit basic ticket information"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash(_('Ticket not found'), 'error')
        return redirect(url_for('main.dashboard'))

    if ticket.current_phase == 'Already Taken':
        flash(_('This ticket is locked and cannot be modified.'), 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))
        
    users = User.query.filter(User.roles.any(Role.name == 'technician')).all()
    
    if request.method == 'POST':
        ticket.items_included = request.form.get('items_included')
        ticket.problem_description = request.form.get('problem_description')
        assigned_to = request.form.get('assigned_to')
        
        # Update assignment safely
        ticket.assigned_to = int(assigned_to) if assigned_to else None
        
        db.session.commit()
        flash(_('Ticket updated successfully!'), 'success')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))
        
    return render_template('edit_ticket.html', ticket=ticket, users=users)

@ticket_bp.route('/archive/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('archive_ticket')
def archive_ticket(ticket_id):
    """Move a completed ticket to archive to keep active records clean"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash(_('Ticket not found'), 'error')
        return redirect(url_for('main.dashboard'))
    
    if ticket.current_phase != 'Already Taken':
        flash(_('Only tickets that are already collected (Already Taken) can be archived.'), 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))
    
    ticket.is_archived = True
    db.session.commit()
    flash(_('Ticket %(num)s has been archived.', num=ticket.ticket_number), 'success')
    return redirect(url_for('ticket.tickets_list', view='history'))

@ticket_bp.route('/delete/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('delete_ticket')
def delete_ticket(ticket_id):
    """Permanently erase a ticket and its associated logs/notes"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash(_('Ticket not found'), 'error')
        return redirect(url_for('main.dashboard'))
    
    db.session.delete(ticket)
    db.session.commit()
    flash(_('Ticket %(num)s has been permanently erased.', num=ticket.ticket_number), 'success')
    return redirect(url_for('main.dashboard'))

@ticket_bp.route('/update_phase/<int:ticket_id>', methods=['POST'])
@login_required
def update_phase(ticket_id):
    """Route to advance the repair ticket through its lifecycle"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket:
        flash(_('Ticket not found'), 'error')
        return redirect(url_for('main.dashboard'))

    if ticket.current_phase == 'Already Taken':
        flash(_('This ticket is locked and cannot be modified.'), 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))

    new_phase = request.form.get('new_phase')
    commentary = request.form.get('commentary', '')

    if not new_phase:
        flash(_('Please select a valid phase'), 'error')
        return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))

    # Dynamic permission check based on target phase
    required_perm = 'update_phase'
    if new_phase == 'Fully Paid':
        required_perm = 'mark_as_paid'
    elif new_phase == 'Already Taken':
        required_perm = 'mark_as_taken'
        
    if not current_user.has_permission(required_perm):
        flash(_('You do not have the required permission (%(perm)s) to move a ticket to "%(phase)s".', perm=required_perm, phase=new_phase), 'error')
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
            note_type=_('Phase Update'),
            content=_('Phase update to %(phase)s: %(comment)s', phase=new_phase, comment=commentary),
            is_internal=True
        )
        db.session.add(note)

    try:
        db.session.commit()
        flash(_('Ticket phase updated to %(phase)s', phase=new_phase), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to update phase for ticket {ticket_id}: {str(e)}")
        flash(_('Error updating ticket phase.'), 'error')
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket.id))

@customer_bp.route('/view/<int:customer_id>', endpoint='view_customer')
@login_required
@require_permission('view_customer')
def view_customer(customer_id):
    """Detailed view for a single customer and their devices"""
    customer = db.session.get(Customer, customer_id)
    if not customer:
        flash(_('Customer not found'), 'error')
        return redirect(url_for('customer.customers_list'))
    try:
        return render_template('customer_detail.html', customer=customer)
    except InvalidToken:
        flash(_('Security Error: Unable to decrypt this customer\'s PII.'), 'error')
        return redirect(url_for('customer.customers_list'))


@customer_bp.route('/new_customer', methods=['GET', 'POST'])
@login_required
@require_permission('create_customer')
def new_customer():
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        address = request.form.get('address', '')
        
        if not name or not phone:
            flash(_('Name and phone are required'), 'error')
        else:
            customer = Customer(name=name, phone=phone, address=address)
            db.session.add(customer)
            db.session.commit()
            flash(_('Customer created successfully!'), 'success')
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
            flash(_('Customer, Type, and Brand are required'), 'error')
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
            flash(_('Device added successfully!'), 'success')
            return redirect(url_for('main.devices_list'))
            
    return render_template('new_device.html', customers=customers)

@device_bp.route('/edit/<int:device_id>', methods=['GET', 'POST'])
@login_required
@require_permission('edit_device')
def edit_device(device_id):
    """Route to edit hardware specifications for a specific device"""
    device = db.session.get(Device, device_id)
    if not device:
        flash(_('Device not found'), 'error')
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
        flash(_('Device updated successfully!'), 'success')
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
        flash(_('Device deleted successfully.'), 'success')
        return redirect(url_for('customer.view_customer', customer_id=customer_id))
    return redirect(url_for('main.devices_list'))

@ticket_bp.route('/download_invoice/<int:ticket_id>')
@login_required
@require_permission('create_invoice')
def download_invoice_pdf(ticket_id):
    """Placeholder for PDF generation logic (Future Feature)"""
    flash(_('PDF generation is currently being implemented. Please use the on-screen invoice view.'), 'info')
    return redirect(url_for('ticket.ticket_detail', ticket_id=ticket_id))

@device_bp.route('/view/<int:device_id>')
@login_required
@require_permission('view_customer')
def device_detail(device_id):
    """Detailed view for a single device repair history"""
    device = db.session.get(Device, device_id)
    if not device:
        flash(_('Device not found'), 'error')
        return redirect(url_for('main.dashboard'))
    return render_template('device_detail.html', device=device)

# ==================== CUSTOMER AJAX ROUTERS (COMPLETING MAIN.JS MATCH) ====================
@customer_bp.route('/search', methods=['GET'])
@login_required
@require_permission('view_customer')
def search_customers():
    """Asynchronous search endpoint requested by main.js customer_search input"""
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([])

    # GDPR Search: Exact matches use the blind index hash for security.
    query_hash = hashlib.sha256((current_app.config['BLIND_INDEX_SALT'] + query).encode()).hexdigest()
        
    customers = Customer.query.filter(
        or_(Customer.name.ilike(f'%{query}%'), Customer.phone_hash == query_hash)
    ).limit(10).all()
    
    return jsonify([{'id': c.id, 'name': c.name, 'phone': c.phone} for c in customers])


@customer_bp.route('/export/<int:customer_id>')
@login_required
@require_permission('view_customer')
def export_customer_data(customer_id):
    """GDPR compliance: Data Portability."""
    customer = db.session.get(Customer, customer_id)
    if not customer:
        flash(_('Customer not found'), 'error')
        return redirect(url_for('customer.customers_list'))
    
    try:
        data = customer.export_data()
        output = io.BytesIO(json.dumps(data, indent=4).encode('utf-8'))
        return send_file(output, mimetype='application/json', as_attachment=True,
                         download_name=f"customer_export_{customer_id}.json")
    except InvalidToken:
        flash(_('Security Error: Decryption failed during data export.'), 'error')
        return redirect(url_for('customer.view_customer', customer_id=customer_id))


@customer_bp.route('/anonymize/<int:customer_id>', methods=['POST'])
@login_required
@require_permission('delete_customer')
def anonymize_customer(customer_id):
    """GDPR compliance: Right to Erasure."""
    customer = db.session.get(Customer, customer_id)
    if not customer:
        flash(_('Customer not found'), 'error')
        return redirect(url_for('customer.customers_list'))
    
    try:
        customer.anonymize()
        db.session.commit()
        flash(_('Customer data has been anonymized successfully.'), 'success')
    except InvalidToken:
        db.session.rollback()
        flash(_('Security Error: Decryption failed during anonymization.'), 'error')
        
    return redirect(url_for('customer.customers_list'))

@customer_bp.route('/new', methods=['POST'])
@login_required
@require_permission('create_customer')
def new_customer_ajax():
    """Asynchronous modal form target managed by saveCustomerBtn click event"""
    name = request.form.get('name')
    phone = request.form.get('phone')
    address = request.form.get('address', '')
    
    if not name or not phone:
        return jsonify({'error': _('Name and phone fields are required')}), 400
        
    try:
        customer = Customer(name=name, phone=phone, address=address)
        db.session.add(customer)
        db.session.commit()
        return jsonify({'id': customer.id, 'name': customer.name})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Ajax customer creation failed: {str(e)}")
        return jsonify({'error': _('Failed to create customer record')}), 500



# ==================== DEVICE AJAX ROUTERS (COMPLETING MAIN.JS MATCH) ====================
@device_bp.route('/search/<int:customer_id>', methods=['GET'])
@login_required
@require_permission('view_customer')
def search_devices(customer_id):
    """Asynchronous search endpoint checking customer context profiles"""
    query = request.args.get('q', '').strip()
    
    # Filter devices bound specifically to the active customer
    device_query = Device.query.filter_by(customer_id=customer_id)
    if query:
        device_query = device_query.filter(
            or_(Device.brand.ilike(f'%{query}%'), Device.model_number.ilike(f'%{query}%'), Device.device_type.ilike(f'%{query}%'))
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
        return jsonify({'error': _('Customer, Type, and Brand are required')}), 400
        
    device = Device(
        customer_id=customer_id,
        device_type=device_type,
        brand=brand,
        model_number=request.form.get('model_number'),
        serial_number=request.form.get('serial_number'),
        color=request.form.get('color'),
        cpu=request.form.get('cpu'),
        ram=request.form.get('ram'),
        storage_type=request.form.get('storage_type'),
        storage_capacity=request.form.get('storage_capacity'),
        notes=request.form.get('notes')
    )
    db.session.add(device)
    db.session.commit()
    
    return jsonify({'id': device.id, 'display': device.display})
    
