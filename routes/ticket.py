from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from models import db, Ticket, Customer, Device, Service, SparePart, Invoice
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

        try:
            ticket = RepairTicketService.create_ticket(
                customer_id=customer_id,
                device_id=device_id,
                location_id=current_user.location_id,
                creator_id=current_user.id,
                items_included=request.form.get('items_included', ''),
                problem_description=request.form.get('problem_description', ''),
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
        
    return render_template('tickets/new_ticket.html')

@ticket_bp.route('/view/<int:ticket_id>')
@login_required
@require_permission('view_ticket')
def view_ticket(ticket_id):
    # Optimization: Eager load relations to prevent N+1 queries in the template
    stmt = select(Ticket).options(
        joinedload(Ticket.customer),
        joinedload(Ticket.device)
    ).where(Ticket.id == ticket_id)
    ticket = db.session.scalar(stmt)

    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Ticket not found'), 'error')
        return redirect(url_for('main.dashboard'))
    
    services = Service.query.filter_by(location_id=current_user.location_id, is_active=True).all()
    parts = SparePart.query.filter_by(location_id=current_user.location_id, is_active=True).all()
    
    return render_template('tickets/view_ticket.html', ticket=ticket, services=services, parts=parts)

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

@ticket_bp.route('/add_service/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('edit_ticket')
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
@require_permission('edit_ticket')
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