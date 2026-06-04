from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user
from sqlalchemy import select, desc, and_
from sqlalchemy.orm import joinedload, selectinload
from models import db, Ticket, Customer, Device, Service, SparePart, Invoice, PhaseLog, Note, User, CommonProblem, Role
from services import RepairTicketService, InventoryService, FinancialService, DocumentService
from .utils import require_permission, safe_decimal
from flask_babel import _

ticket_bp = Blueprint('ticket', __name__)

@ticket_bp.route('/new', methods=['GET', 'POST'])
@login_required
@require_permission('create_ticket')
def new_ticket():
    if request.method == 'POST':
        customer_id = request.form.get('customer_id', type=int)
        device_id = request.form.get('device_id', type=int)
        
        # Validation: Ensure customer belongs to this location
        customer = db.session.get(Customer, customer_id)
        if not customer or (not current_user.is_superuser and customer.location_id != current_user.location_id):
            flash(_('Invalid customer selection.'), 'error')
            return redirect(url_for('ticket.new_ticket'))

        # Validation: Ensure device belongs to the selected customer
        device = db.session.get(Device, device_id)
        if not device or device.customer_id != customer_id:
            flash(_('Invalid device selection for this customer.'), 'error')
            return redirect(url_for('ticket.new_ticket'))

        # Handle Backdating (Optional Date/Time from form)
        created_at = None
        date_str = request.form.get('created_date')
        time_str = request.form.get('created_time')
        if date_str and time_str:
            try:
                created_at = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            except ValueError:
                created_at = None

        try:
            ticket = RepairTicketService.create_ticket(
                customer_id=customer_id,
                device_id=device_id,
                location_id=current_user.location_id,
                creator_id=current_user.id,
                items_included=request.form.get('items_included', ''),
                problem_description=request.form.get('problem_description', ''),
                assigned_to=request.form.get('assigned_to', type=int) or None,
                created_at=created_at,
                down_payment=safe_decimal(request.form.get('down_payment', '0.00')),
                payment_method=request.form.get('payment_method')
            )
            db.session.commit()
            flash(_('Ticket %(num)s created successfully!', num=ticket.ticket_number), 'success')
            return redirect(url_for('ticket.view_ticket', ticket_id=ticket.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Ticket creation failed: {str(e)}")
            flash(_('An error occurred while creating the ticket.'), 'error')
            return redirect(url_for('ticket.new_ticket'))
        
    # Fetch context for the intake form
    common_problems = db.session.execute(db.select(CommonProblem).filter_by(location_id=current_user.location_id, is_active=True)).scalars().all()
    # Integrity Fix: Only fetch users with the 'technician' role for assignment
    users_stmt = db.select(User).join(User.roles).where(
        User.location_id == current_user.location_id,
        User.is_active == True,
        Role.name == 'technician'
    )
    users = db.session.execute(users_stmt).scalars().all()
    now = datetime.now()
    
    return render_template('tickets/new_ticket.html', common_problems=common_problems, users=users, 
                           now_date=now.strftime('%Y-%m-%d'), now_time=now.strftime('%H:%M'))

@ticket_bp.route('/view/<int:ticket_id>')
@login_required
@require_permission('view_ticket')
def view_ticket(ticket_id):
    # Optimization: Eager load relations including audit logs and notes for the timeline UI
    stmt = select(Ticket).options(
        joinedload(Ticket.customer),
        joinedload(Ticket.device),
        selectinload(Ticket.phase_logs).joinedload(PhaseLog.technician_user),
        selectinload(Ticket.notes).joinedload(Note.author)
    ).where(Ticket.id == ticket_id)
    ticket = db.session.scalar(stmt)

    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Ticket not found'), 'error')
        return redirect(url_for('main.dashboard'))
    
    services = db.session.execute(db.select(Service).filter_by(location_id=current_user.location_id, is_active=True)).scalars().all()
    parts = db.session.execute(db.select(SparePart).filter_by(location_id=current_user.location_id, is_active=True)).scalars().all()
    
    return render_template('tickets/ticket_detail.html', ticket=ticket, services=services, parts=parts)

@ticket_bp.route('/list')
@login_required
@require_permission('view_ticket')
def tickets_list():
    """Comprehensive repository view for all branch tickets"""
    page = request.args.get('page', 1, type=int)
    view = request.args.get('view', 'active')
    
    filters = []
    if not current_user.is_superuser:
        filters.append(Ticket.location_id == current_user.location_id)
    
    filters.append(Ticket.is_archived == (True if view == 'history' else False))

    stmt = select(Ticket).options(
        joinedload(Ticket.customer), 
        joinedload(Ticket.device),
        joinedload(Ticket.assigned_to_user)
    ).where(and_(*filters)).order_by(desc(Ticket.created_at))
    
    tickets = db.paginate(stmt, page=page, per_page=20)
    return render_template('tickets/tickets_list.html', tickets=tickets, current_view=view)

@ticket_bp.route('/edit/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
@require_permission('edit_ticket')
def edit_ticket(ticket_id):
    """Allows correction of initial intake data"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Ticket not found'), 'error')
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        ticket.items_included = request.form.get('items_included')
        ticket.problem_description = request.form.get('problem_description')
        ticket.assigned_to = request.form.get('assigned_to', type=int) or None
        db.session.commit()
        flash(_('Ticket intake data updated successfully.'), 'success')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket.id))
        
    # Integrity Fix: Consistency check for technician assignment during edit
    users_stmt = db.select(User).join(User.roles).where(
        User.location_id == current_user.location_id,
        User.is_active == True,
        Role.name == 'technician'
    )
    users = db.session.execute(users_stmt).scalars().all()
    return render_template('tickets/edit_ticket.html', ticket=ticket, users=users)

@ticket_bp.route('/update_phase/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('edit_ticket')
def update_phase(ticket_id):
    new_phase = request.form.get('phase')
    commentary = request.form.get('commentary')

    ticket = db.session.get(Ticket, ticket_id)
    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'error')
        return redirect(url_for('main.dashboard'))
    
    success, result = RepairTicketService.update_phase(ticket_id, new_phase, current_user.id, commentary)
    if success:
        db.session.commit()
        flash(_('Ticket status updated to %(phase)s', phase=new_phase), 'success')
    else:
        flash(result, 'error')
        
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/invoice/<int:ticket_id>')
@login_required
@require_permission('view_ticket')
def view_invoice(ticket_id):
    """Renders the HTML version of the invoice for viewing/printing"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Ticket not found'), 'error')
        return redirect(url_for('main.dashboard'))
    
    # Ensure an invoice record exists for the ticket
    invoice = FinancialService.get_or_create_invoice(ticket_id)
    return render_template('tickets/invoice.html', invoice=invoice)

@ticket_bp.route('/invoice/download/<int:ticket_id>')
@login_required
@require_permission('view_ticket')
def download_invoice_pdf(ticket_id):
    """Triggers the DocumentService to generate and stream a PDF invoice"""
    success, result = DocumentService.generate_invoice_pdf(ticket_id)
    if success:
        return send_file(
            result,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"invoice_{ticket_id}.pdf"
        )
    flash(result, 'error')
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/add_service/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('add_service')
def add_service(ticket_id):
    service_id = request.form.get('service_id', type=int)
    quantity = request.form.get('quantity', 1, type=int)

    ticket = db.session.get(Ticket, ticket_id)
    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'error')
        return redirect(url_for('main.dashboard'))
    
    success, result = InventoryService.add_service_to_ticket(ticket_id, service_id, quantity)
    if success:
        db.session.commit()
        flash(_('Service added.'), 'success')
    else:
        flash(result, 'error')
        
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/add_part/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('add_part')
def add_part(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'error')
        return redirect(url_for('main.dashboard'))

    success, result = InventoryService.add_part_to_ticket(
        ticket_id=ticket_id,
        part_id=request.form.get('part_id', type=int) if request.form.get('part_id') else None,
        manual_name=request.form.get('manual_name'),
        quantity=request.form.get('quantity', 1, type=int),
        price=safe_decimal(request.form.get('price')) if request.form.get('price') else None,
        cost=safe_decimal(request.form.get('cost')) if request.form.get('cost') else None
    )
    
    if success:
        db.session.commit()
        flash(_('Part added.'), 'success')
    else:
        flash(result, 'error')
        
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/payment/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('process_payments')
def record_payment(ticket_id):
    amount = safe_decimal(request.form.get('amount'))
    method = request.form.get('method')
    reference = request.form.get('reference', '')

    ticket = db.session.get(Ticket, ticket_id)
    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'error')
        return redirect(url_for('main.dashboard'))
    
    success, result = FinancialService.record_payment(ticket_id, amount, method, reference, current_user.id)
    if success:
        db.session.commit()
        flash(_('Payment recorded successfully.'), 'success')
    else:
        flash(result, 'error')
        
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/payment/void/<int:ticket_id>/<int:payment_id>', methods=['POST'])
@login_required
@require_permission('process_payments')
def void_payment(ticket_id, payment_id):
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'error')
        return redirect(url_for('main.dashboard'))
    
    success, result = FinancialService.void_payment(payment_id, current_user.id)
    if success:
        db.session.commit()
        flash(result, 'success')
    else:
        flash(result, 'error')
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/remove_service/<int:ticket_id>/<int:ts_id>', methods=['POST'])
@login_required
@require_permission('remove_service')
def remove_service(ticket_id, ts_id):
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'error')
        return redirect(url_for('main.dashboard'))
    
    success, result = InventoryService.remove_service(ticket_id, ts_id)
    if success:
        db.session.commit()
        flash(_('Service removed.'), 'success')
    else:
        flash(result, 'error')
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/remove_part/<int:ticket_id>/<int:item_id>', methods=['POST'])
@login_required
@require_permission('remove_part')
def remove_part(ticket_id, item_id):
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'error')
        return redirect(url_for('main.dashboard'))

    success, result = InventoryService.remove_part(item_id)
    if success:
        db.session.commit()
        flash(_('Part removed and stock restored.'), 'success')
    else:
        flash(result, 'error')
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/archive/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('archive_ticket')
def archive_ticket(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    if ticket and (current_user.is_superuser or ticket.location_id == current_user.location_id):
        ticket.is_archived = True
        db.session.commit()
        flash(_('Ticket archived.'), 'success')
        return redirect(url_for('ticket.tickets_list', view='history'))
    return redirect(url_for('main.dashboard'))

@ticket_bp.route('/delete/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('delete_ticket')
def delete_ticket(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    if ticket and (current_user.is_superuser or ticket.location_id == current_user.location_id):
        db.session.delete(ticket)
        db.session.commit()
        flash(_('Ticket permanently erased.'), 'success')
        return redirect(url_for('ticket.tickets_list'))
    return redirect(url_for('main.dashboard'))

@ticket_bp.route('/invoice/create/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('create_invoice')
def create_invoice(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Ticket not found'), 'error')
        return redirect(url_for('main.dashboard'))
    
    invoice = FinancialService.get_or_create_invoice(ticket_id)
    if invoice.status == 'Draft':
        invoice.status = 'Unpaid'
    db.session.commit()
    flash(_('Invoice generated successfully.'), 'success')
    return redirect(url_for('ticket.view_invoice', ticket_id=ticket_id))