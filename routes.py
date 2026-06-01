from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user, login_user, logout_user
from datetime import datetime
from sqlalchemy import desc, or_
from models import db, User, Role, Permission, Customer, Device, Ticket, Note, Payment, PhaseLog, Service, SparePart, Invoice, InvoiceItem, TicketService, CommonProblem, Backup
import uuid
from functools import wraps
import json
import io
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from flask import send_file

# Create blueprints
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
            if theme in ['light', 'dark']:
                current_user.theme_preference = theme
                db.session.commit()
                flash('Theme changed successfully!', 'success')
        
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
    
    # Get current month stats
    from datetime import date
    today = date.today()
    current_month_start = today.replace(day=1)
    
    stats = {
        'total_tickets': Ticket.query.count(),
        'open_tickets': Ticket.query.filter_by(current_phase='Open').count() or 0,
        'diagnostic': Ticket.query.filter_by(current_phase='Diagnostic').count() or 0,
        'repairing': Ticket.query.filter_by(current_phase='Repairing').count() or 0,
        'finished': Ticket.query.filter_by(current_phase='Finished').count() or 0,
        'total_customers': Customer.query.count(),
    }
    
    return render_template('dashboard.html', tickets=tickets, stats=stats, current_theme=current_user.theme_preference)


# ==================== TICKET ROUTES ====================
@ticket_bp.route('/new', methods=['GET', 'POST'])
@login_required
@require_permission('create_ticket')
def new_ticket():
    customers = Customer.query.order_by(desc(Customer.created_at)).all()
    users = User.query.filter(User.role.any(Role.name == 'technician')).all()
    common_problems = CommonProblem.query.filter_by(is_active=True).all()
    
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        device_id = request.form.get('device_id')
        items_included = request.form.get('items_included')
        problem_description = request.form.get('problem_description')
        assigned_to = request.form.get('assigned_to')
        created_date = request.form.get('created_date')
        created_time = request.form.get('created_time')
        down_payment = request.form.get('down_payment', 0)
        
        # Validate inputs
        if not device_id:
            flash('Please select a device', 'error')
            return redirect(url_for('ticket.new_ticket'))
        
        # Combine date and time
        try:
            created_datetime = datetime.strptime(f"{created_date} {created_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            flash('Invalid date or time format', 'error')
            return redirect(url_for('ticket.new_ticket'))
        
        # Generate unique ticket number
        ticket_number = f"TKT-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        
        device = Device.query.get(device_id)
        
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
        db.session.flush()
        
        # Create initial phase log
        initial_log = PhaseLog(
            ticket_id=ticket.id,
            user_id=current_user.id,
            phase='Open',
            commentary='Ticket created and device received'
        )
        db.session.add(initial_log)
        
        # Record down payment if provided
        if down_payment and float(down_payment) > 0:
            payment = Payment(
                ticket_id=ticket.id,
                user_id=current_user.id,
                amount=float(down_payment),
                payment_type='Down Payment',
                payment_method='Cash'
            )
            db.session.add(payment)
            
            note = Note(
                ticket_id=ticket.id,
                user_id=current_user.id,
                note_type='Down Payment',
                content=f'Down Payment: ${down_payment}'
            )
            db.session.add(note)
        
        db.session.commit()
        
        flash(f'Ticket {ticket_number} created successfully!', 'success')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket.id))
    
    return render_template('new_ticket.html', customers=customers, users=users, common_problems=common_problems)


@ticket_bp.route('/<int:ticket_id>', methods=['GET'])
@login_required
@require_permission('view_ticket')
def view_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    return render_template('ticket_detail.html', ticket=ticket)


@ticket_bp.route('/<int:ticket_id>/phase', methods=['POST'])
@login_required
@require_permission('update_phase')
def update_phase(ticket_id):
    """Update ticket phase and log the change"""
    ticket = Ticket.query.get_or_404(ticket_id)
    phase = request.form.get('phase')
    commentary = request.form.get('commentary')
    
    if not phase or phase not in ticket.PHASE_CHOICES:
        flash('Invalid phase selected', 'error')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))
    
    # Create phase log with timestamp
    phase_log = PhaseLog(
        ticket_id=ticket_id,
        user_id=current_user.id,
        phase=phase,
        commentary=commentary,
        timestamp=datetime.utcnow()
    )
    
    # Update current phase
    ticket.current_phase = phase
    if phase == 'Finished':
        ticket.completed_at = datetime.utcnow()
    
    db.session.add(phase_log)
    db.session.commit()
    
    flash(f'Ticket moved to {phase} phase!', 'success')
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))


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


@ticket_bp.route('/<int:ticket_id>/service/add', methods=['POST'])
@login_required
@require_permission('add_service')
def add_service_to_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    service_id = request.form.get('service_id')
    quantity = request.form.get('quantity', 1, type=int)
    
    service = Service.query.get_or_404(service_id)
    
    ticket_service = TicketService(
        ticket_id=ticket_id,
        service_id=service_id,
        quantity=quantity,
        price=service.price
    )
    
    db.session.add(ticket_service)
    db.session.commit()
    
    flash(f'Service {service.name} added to ticket!', 'success')
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))


# ==================== CUSTOMER ROUTES ====================
@customer_bp.route('/')
@login_required
@require_permission('view_customer')
def customers_list():
    page = request.args.get('page', 1, type=int)
    customers = Customer.query.order_by(desc(Customer.created_at)).paginate(page=page, per_page=20)
    return render_template('customers.html', customers=customers)


@customer_bp.route('/search')
@login_required
def search_customers():
    """API endpoint to search customers"""
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([])
    
    customers = Customer.query.filter(
        or_(Customer.name.ilike(f'%{query}%'), Customer.phone.ilike(f'%{query}%'))
    ).order_by(desc(Customer.created_at)).limit(10).all()
    
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'phone': c.phone
    } for c in customers])


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
        
        # Return JSON if called from modal
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'id': customer.id, 'name': customer.name})
        
        return redirect(url_for('customer.customers_list'))
    
    return render_template('new_customer.html')


@customer_bp.route('/<int:customer_id>', methods=['GET'])
@login_required
@require_permission('view_customer')
def view_customer(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    return render_template('customer_detail.html', customer=customer)


# ==================== DEVICE ROUTES ====================
@device_bp.route('/search/<int:customer_id>')
@login_required
def search_devices(customer_id):
    """API endpoint to search customer devices"""
    query = request.args.get('q', '').strip()
    devices = Device.query.filter_by(customer_id=customer_id)
    
    if query:
        devices = devices.filter(
            or_(Device.brand.ilike(f'%{query}%'), Device.model.ilike(f'%{query}%'))
        )
    
    return jsonify([{
        'id': d.id,
        'display': f"{d.brand} {d.model} ({d.device_type})",
        'brand': d.brand,
        'model': d.model,
        'device_type': d.device_type
    } for d in devices.all()])


@device_bp.route('/new', methods=['GET', 'POST'])
@login_required
@require_permission('create_device')
def new_device():
    customer_id = request.args.get('customer_id')
    
    if request.method == 'POST':
        customer_id = request.form.get('customer_id')
        device_type = request.form.get('device_type')
        brand = request.form.get('brand')
        model = request.form.get('model')
        model_number = request.form.get('model_number')
        cpu = request.form.get('cpu')
        ram = request.form.get('ram')
        storage_type = request.form.get('storage_type')
        storage_capacity = request.form.get('storage_capacity')
        serial_number = request.form.get('serial_number')
        color = request.form.get('color')
        notes = request.form.get('notes')
        
        device = Device(
            customer_id=customer_id,
            device_type=device_type,
            brand=brand,
            model=model,
            model_number=model_number,
            cpu=cpu,
            ram=ram,
            storage_type=storage_type,
            storage_capacity=storage_capacity,
            serial_number=serial_number,
            color=color,
            notes=notes
        )
        
        db.session.add(device)
        db.session.commit()
        
        flash(f'Device {brand} {model} added successfully!', 'success')
        
        # Return JSON if called from modal
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'id': device.id, 'display': f"{brand} {model}"})
        
        return redirect(url_for('customer.view_customer', customer_id=customer_id))
    
    customer = Customer.query.get_or_404(customer_id) if customer_id else None
    return render_template('new_device.html', customer=customer, customer_id=customer_id)


@device_bp.route('/<int:device_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('edit_device')
def edit_device(device_id):
    device = Device.query.get_or_404(device_id)
    
    if request.method == 'POST':
        device.device_type = request.form.get('device_type')
        device.brand = request.form.get('brand')
        device.model = request.form.get('model')
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


@device_bp.route('/<int:device_id>/delete', methods=['POST'])
@login_required
@require_permission('delete_device')
def delete_device(device_id):
    device = Device.query.get_or_404(device_id)
    customer_id = device.customer_id
    
    db.session.delete(device)
    db.session.commit()
    
    flash('Device deleted successfully!', 'success')
    return redirect(url_for('customer.view_customer', customer_id=customer_id))


# ==================== INVOICE ROUTES ====================
@ticket_bp.route('/<int:ticket_id>/invoice', methods=['GET'])
@login_required
@require_permission('view_ticket')
def view_invoice(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    invoice = ticket.invoice
    
    if not invoice:
        flash('No invoice created yet', 'error')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))
    
    return render_template('invoice.html', ticket=ticket, invoice=invoice)


@ticket_bp.route('/<int:ticket_id>/invoice/create', methods=['POST'])
@login_required
@require_permission('create_invoice')
def create_invoice(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    
    # Check if invoice already exists
    if ticket.invoice:
        flash('Invoice already created for this ticket', 'error')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))
    
    # Calculate totals
    services_total = sum(ts.price * ts.quantity for ts in ticket.ticket_services)
    
    invoice_number = f"INV-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    
    invoice = Invoice(
        invoice_number=invoice_number,
        ticket_id=ticket_id,
        subtotal=services_total,
        total_amount=services_total
    )
    
    db.session.add(invoice)
    db.session.commit()
    
    flash('Invoice created successfully!', 'success')
    return redirect(url_for('ticket.view_invoice', ticket_id=ticket_id))


@ticket_bp.route('/<int:ticket_id>/invoice/pdf', methods=['GET'])
@login_required
@require_permission('view_ticket')
def download_invoice_pdf(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    invoice = ticket.invoice
    
    if not invoice:
        flash('No invoice created yet', 'error')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))
    
    # Create PDF
    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1f4788'),
        spaceAfter=30
    )
    
    # Title
    elements.append(Paragraph("REPAIR INVOICE", title_style))
    elements.append(Spacer(1, 0.3*inch))
    
    # Invoice info
    info_data = [
        ['Invoice Number:', invoice.invoice_number, 'Date:', invoice.issued_date.strftime('%Y-%m-%d')],
        ['Ticket Number:', ticket.ticket_number, 'Status:', invoice.status],
    ]
    info_table = Table(info_data, colWidths=[1.5*inch, 2*inch, 1.5*inch, 2*inch])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Customer info
    customer_data = [
        ['CUSTOMER INFORMATION', ''],
        ['Name:', ticket.customer.name],
        ['Phone:', ticket.customer.phone],
        ['Device:', f"{ticket.device.brand} {ticket.device.model}"],
    ]
    customer_table = Table(customer_data, colWidths=[2*inch, 4*inch])
    customer_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4788')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(customer_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Services
    if ticket.ticket_services:
        service_data = [['Service', 'Quantity', 'Unit Price', 'Total']]
        for ts in ticket.ticket_services:
            service_data.append([
                ts.service.name,
                str(ts.quantity),
                f"${ts.price:.2f}",
                f"${ts.price * ts.quantity:.2f}"
            ])
        
        service_table = Table(service_data, colWidths=[3*inch, 1*inch, 1.5*inch, 1.5*inch])
        service_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4788')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(service_table)
        elements.append(Spacer(1, 0.2*inch))
    
    # Spare parts
    if invoice.items:
        spare_data = [['Spare Part', 'Quantity', 'Unit Price', 'Total']]
        for item in invoice.items:
            spare_data.append([
                item.spare_part.name,
                str(item.quantity),
                f"${item.unit_price:.2f}",
                f"${item.total_price:.2f}"
            ])
        
        spare_table = Table(spare_data, colWidths=[3*inch, 1*inch, 1.5*inch, 1.5*inch])
        spare_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e74c3c')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(spare_table)
        elements.append(Spacer(1, 0.2*inch))
    
    # Totals
    total_data = [
        ['Subtotal (Services):', f"${invoice.subtotal:.2f}"],
        ['Subtotal (Spare Parts):', f"${invoice.spare_parts_total:.2f}"],
        ['Total Amount:', f"${invoice.total_amount:.2f}"],
        ['Down Payment:', f"${invoice.down_payment:.2f}"],
        ['Amount Paid:', f"${invoice.full_payment_received:.2f}"],
        ['Remaining Balance:', f"${invoice.remaining_balance:.2f}"],
    ]
    total_table = Table(total_data, colWidths=[4*inch, 2*inch])
    total_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 4), 'Helvetica'),
        ('FONTNAME', (0, 5), (-1, 5), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 4), 10),
        ('FONTSIZE', (0, 5), (-1, 5), 12),
        ('BACKGROUND', (0, 5), (-1, 5), colors.HexColor('#1f4788')),
        ('TEXTCOLOR', (0, 5), (-1, 5), colors.whitesmoke),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(total_table)
    
    doc.build(elements)
    pdf_buffer.seek(0)
    
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"{invoice.invoice_number}.pdf"
    )


# ==================== REPORT ROUTES ====================
@report_bp.route('/')
@login_required
@require_permission('view_reports')
def reports():
    """Main reports page"""
    from datetime import date, timedelta
    
    today = date.today()
    current_month_start = today.replace(day=1)
    
    # Monthly stats
    monthly_stats = {
        'total_tickets': Ticket.query.filter(Ticket.created_at >= current_month_start).count(),
        'completed_tickets': Ticket.query.filter(
            Ticket.current_phase == 'Finished',
            Ticket.created_at >= current_month_start
        ).count(),
        'total_revenue': sum(p.amount for p in Payment.query.filter(Payment.created_at >= current_month_start).all()),
    }
    
    # Recent tickets
    recent_tickets = Ticket.query.order_by(desc(Ticket.created_at)).limit(10).all()
    
    return render_template('reports.html', monthly_stats=monthly_stats, recent_tickets=recent_tickets)


# ==================== DEVICES TAB ====================
@main_bp.route('/devices')
@login_required
@require_permission('view_customer')
def devices_list():
    """Dedicated devices tab showing all devices"""
    page = request.args.get('page', 1, type=int)
    devices = Device.query.order_by(desc(Device.created_at)).paginate(page=page, per_page=20)
    return render_template('devices.html', devices=devices)


# ==================== COMMON PROBLEMS ====================
@admin_bp.route('/common-problems', methods=['GET', 'POST'])
@login_required
@require_superuser()
def manage_common_problems():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            problem_text = request.form.get('problem_text')
            problem = CommonProblem(problem_text=problem_text, is_active=True)
            db.session.add(problem)
            db.session.commit()
            flash('Common problem added successfully!', 'success')
        
        elif action == 'delete':
            problem_id = request.form.get('problem_id')
            problem = CommonProblem.query.get_or_404(problem_id)
            db.session.delete(problem)
            db.session.commit()
            flash('Common problem deleted successfully!', 'success')
        
        return redirect(url_for('admin.manage_common_problems'))
    
    problems = CommonProblem.query.filter_by(is_active=True).all()
    return render_template('admin/manage_common_problems.html', problems=problems)


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
    
    # Group permissions by category
    permissions_by_category = {}
    for perm in all_permissions:
        category = perm.category or 'Other'
        if category not in permissions_by_category:
            permissions_by_category[category] = []
        permissions_by_category[category].append(perm)
    
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
    
    return render_template('admin/edit_user.html', user=user, roles=roles, permissions_by_category=permissions_by_category)


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


@admin_bp.route('/backup', methods=['GET', 'POST'])
@login_required
@require_superuser()
def manage_backup():
    """Backup and restore database"""
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'backup':
            # Create backup JSON
            backup_data = {
                'users': [u.username for u in User.query.all()],
                'customers': [c.name for c in Customer.query.all()],
                'devices': [f"{d.brand} {d.model}" for d in Device.query.all()],
                'tickets': [t.ticket_number for t in Ticket.query.all()],
                'timestamp': datetime.now().isoformat()
            }
            
            backup = Backup(
                backup_name=f"Backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                backup_data=json.dumps(backup_data),
                file_size=f"{len(json.dumps(backup_data))} bytes",
                created_by=current_user.id
            )
            
            db.session.add(backup)
            db.session.commit()
            
            flash('Backup created successfully!', 'success')
        
        return redirect(url_for('admin.manage_backup'))
    
    backups = Backup.query.order_by(desc(Backup.created_at)).all()
    return render_template('admin/backup.html', backups=backups)


@admin_bp.route('/backup/download/<int:backup_id>')
@login_required
@require_superuser()
def download_backup(backup_id):
    """Download backup file"""
    backup = Backup.query.get_or_404(backup_id)
    
    return send_file(
        io.BytesIO(backup.backup_data.encode()),
        mimetype='application/json',
        as_attachment=True,
        download_name=f"{backup.backup_name}.json"
    )


@admin_bp.route('/get-devices/<int:customer_id>')
@login_required
def get_customer_devices(customer_id):
    """API endpoint to get customer devices"""
    devices = Device.query.filter_by(customer_id=customer_id).all()
    return jsonify([{
        'id': d.id,
        'display': f"{d.brand} {d.model} ({d.device_type})"
    } for d in devices])
