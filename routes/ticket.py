from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app
from flask_login import login_required, current_user
from sqlalchemy import select, desc, and_
from sqlalchemy.orm import joinedload, selectinload
from models import db, Ticket, Customer, Device, Service, SparePart, Invoice, PhaseLog, Note, User, CommonProblem, Role, Payment, InvoiceItem
from services import RepairTicketService, InventoryService, FinancialService, DocumentService
from .utils import require_permission, safe_decimal
from flask_babel import _

ticket_bp = Blueprint('ticket', __name__)

@ticket_bp.route('/new', methods=['GET', 'POST'])
@login_required
@require_permission('create_ticket')
def new_ticket():
    # Fetch context needed for both GET and failed POST rendering
    loc_filter = CommonProblem.location_id == current_user.location_id if not current_user.is_superuser else True
    common_problems = db.session.scalars(db.select(CommonProblem).where(loc_filter, CommonProblem.is_active == True)).all()
    
    # Integrity Fix: Only fetch users with the 'technician' role for assignment within current context
    user_loc_filter = User.location_id == current_user.location_id if not current_user.is_superuser else True
    users_stmt = db.select(User).join(User.roles).where(
        user_loc_filter,
        User.is_active == True,
        Role.name == 'technician'
    )
    users = db.session.scalars(users_stmt).all()
    now = datetime.now()

    if request.method == 'POST':
        customer_id = request.form.get('customer_id', type=int)
        device_id = request.form.get('device_id', type=int)
        items_included = request.form.get('items_included', '').strip()
        problem_description = request.form.get('problem_description', '').strip()
        
        # Validation: Ensure customer belongs to this location
        customer = db.session.get(Customer, customer_id)
        if not customer or (not current_user.is_superuser and customer.location_id != current_user.location_id):
            flash(_('Invalid customer selection.'), 'error')
        elif not (device := db.session.get(Device, device_id)):
            flash(_('Invalid device selection.'), 'error')
        elif device.customer_id != customer_id:
            flash(_('Invalid device selection for this customer.'), 'error')
        elif (dp := safe_decimal(request.form.get('down_payment', '0.00'))) < 0:
            flash(_('Down payment cannot be negative.'), 'error')
        else:
            assigned_to = request.form.get('assigned_to', type=int) or None
            is_valid = True
            
            if assigned_to:
                tech = db.session.get(User, assigned_to)
                if not tech or (not current_user.is_superuser and tech.location_id != (current_user.location_id or customer.location_id)):
                    flash(_('Invalid technician assignment.'), 'error')
                    is_valid = False
            
            if is_valid:
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
                    # SCALABILITY: Fallback to customer location if superuser is not assigned to a specific branch
                    ticket = RepairTicketService.create_ticket(
                        customer_id=customer_id,
                        device_id=device_id,
                        location_id=current_user.location_id or customer.location_id,
                        creator_id=current_user.id,
                        items_included=items_included,
                        problem_description=problem_description,
                        assigned_to=assigned_to,
                        created_at=created_at,
                        down_payment=dp,
                        payment_method=request.form.get('payment_method')
                    )
                    db.session.commit()
                    flash(_('Ticket %(num)s created successfully!', num=ticket.ticket_number), 'success')
                    return redirect(url_for('ticket.view_ticket', ticket_id=ticket.id))
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Ticket creation failed: {str(e)}")
                    flash(_('An error occurred while creating the ticket.'), 'error')

        # UX Integrity: Return form data on validation error to prevent data loss
        return render_template('tickets/new_ticket.html', 
                               common_problems=common_problems, 
                               users=users, 
                               now_date=request.form.get('created_date', now.strftime('%Y-%m-%d')), 
                               now_time=request.form.get('created_time', now.strftime('%H:%M')),
                               customer_id=customer_id,
                               device_id=device_id,
                               items_included=items_included,
                               problem_description=problem_description,
                               down_payment=request.form.get('down_payment'),
                               payment_method=request.form.get('payment_method'),
                               assigned_to=request.form.get('assigned_to', type=int))
    
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
        joinedload(Ticket.creator),
        joinedload(Ticket.assigned_to_user),
        selectinload(Ticket.payments),
        selectinload(Ticket.phase_logs).joinedload(PhaseLog.technician_user),
        selectinload(Ticket.notes).joinedload(Note.author)
    ).where(Ticket.id == ticket_id)
    ticket = db.session.scalar(stmt)

    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Ticket not found'), 'error')
        return redirect(url_for('main.dashboard'))
    
    # FIXED: Context-aware lookup for services and parts based on the ticket's branch
    # This allows global admins to see appropriate options for the specific location.
    services = db.session.scalars(db.select(Service).filter_by(location_id=ticket.location_id, is_active=True)).all()
    parts = db.session.scalars(db.select(SparePart).filter_by(location_id=ticket.location_id, is_active=True)).all()
    
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
        joinedload(Ticket.creator),
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
    
    # Context lookup for technicians (defined early for use in all return paths)
    user_loc_filter = User.location_id == ticket.location_id if not current_user.is_superuser else True
    users = db.session.scalars(db.select(User).join(User.roles).where(
        user_loc_filter, User.is_active == True, Role.name == 'technician'
    )).all()

    if request.method == 'POST':
        ticket.items_included = request.form.get('items_included', '').strip()
        ticket.problem_description = request.form.get('problem_description', '').strip()
        new_assigned_to = request.form.get('assigned_to', type=int) or None
        ticket.assigned_to = new_assigned_to
        
        # Integrity Fix: Validate technician assignment context
        if new_assigned_to:
            tech = db.session.get(User, new_assigned_to)
            if not tech or (not current_user.is_superuser and tech.location_id != ticket.location_id):
                flash(_('Invalid technician assignment.'), 'error')
                return render_template('tickets/edit_ticket.html', 
                                       ticket=ticket, 
                                       users=users,
                                       items_included=request.form.get('items_included', '').strip(),
                                       problem_description=request.form.get('problem_description', '').strip(),
                                       assigned_to=request.form.get('assigned_to', type=int))

        try:
            db.session.commit()
            flash(_('Ticket intake data updated successfully.'), 'success')
            return redirect(url_for('ticket.view_ticket', ticket_id=ticket.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Ticket edit failed: {str(e)}")
            flash(_('Error updating ticket data.'), 'error')
            return render_template('tickets/edit_ticket.html', 
                                   ticket=ticket, 
                                   users=users,
                                   items_included=request.form.get('items_included', '').strip(),
                                   problem_description=request.form.get('problem_description', '').strip(),
                                   assigned_to=request.form.get('assigned_to', type=int))

    return render_template('tickets/edit_ticket.html', ticket=ticket, users=users)

@ticket_bp.route('/update_phase/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('edit_ticket')
def update_phase(ticket_id):
    new_phase = request.form.get('phase')
    commentary = request.form.get('commentary', '').strip()

    ticket = db.session.get(Ticket, ticket_id)
    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'error')
        return redirect(url_for('main.dashboard'))
    
    try:
        success, result = RepairTicketService.update_phase(ticket_id, new_phase, current_user.id, commentary)
        if success:
            db.session.commit()
            flash(_('Ticket status updated to %(phase)s', phase=new_phase), 'success')
        else:
            flash(result, 'error')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Phase update error: {str(e)}")
        flash(_('An unexpected error occurred during status update.'), 'error')
        
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

    # INTEGRITY: Always recalculate and sync status for active/unpaid invoices
    if invoice.status != 'Paid' or ticket.balance_due != 0: # Check for any remaining balance, positive or negative
        try:
            invoice.calculate_total()
            if ticket.balance_due <= 0:
                invoice.status = 'Paid'
            elif ticket.total_paid > 0:
                invoice.status = 'Partial'
            else:
                invoice.status = 'Unpaid'
            db.session.commit()
            db.session.refresh(invoice)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Invoice status sync failed: {str(e)}")

    return render_template('tickets/invoice.html', invoice=invoice)

@ticket_bp.route('/invoice/download/<int:ticket_id>')
@login_required
@require_permission('view_ticket')
def download_invoice_pdf(ticket_id):
    """Triggers the DocumentService to generate and stream a PDF invoice"""
    ticket = db.session.get(Ticket, ticket_id)
    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Ticket not found'), 'error')
        return redirect(url_for('main.dashboard'))

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

    if not service_id:
        flash(_('Please select a service.'), 'error')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    if quantity < 1:
        flash(_('Quantity must be at least 1.'), 'error')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))
    
    service = db.session.get(Service, service_id)
    if not service or service.location_id != ticket.location_id:
        flash(_('Invalid service selection.'), 'error')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    success, result = InventoryService.add_service_to_ticket(ticket_id, service_id, quantity)
    if success:
        try:
            # INTEGRITY: Synchronize invoice totals within the same transaction
            invoice = db.session.scalar(select(Invoice).filter_by(ticket_id=ticket_id))
            if invoice:
                invoice.calculate_total()
                if ticket.balance_due <= 0:
                    invoice.status = 'Paid'
                elif ticket.total_paid > 0:
                    invoice.status = 'Partial'
                else:
                    invoice.status = 'Unpaid'

            db.session.commit()
            flash(_('Service added.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Service addition error: {str(e)}")
            flash(_('Error saving service addition.'), 'error')
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

    quantity = request.form.get('quantity', 1, type=int)
    if quantity < 1:
        flash(_('Quantity must be at least 1.'), 'error')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    if not request.form.get('part_id') and not request.form.get('manual_name', '').strip():
        flash(_('Please select a part or enter a manual description.'), 'error')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    part_id = request.form.get('part_id', type=int)
    if part_id:
        part = db.session.get(SparePart, part_id)
        if not part or part.location_id != ticket.location_id:
            flash(_('Invalid part selection.'), 'error')
            return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    success, result = InventoryService.add_part_to_ticket(
        ticket_id=ticket_id,
        part_id=part_id,
        manual_name=request.form.get('manual_name', '').strip(),
        quantity=quantity,
        price=safe_decimal(request.form.get('price')) if request.form.get('price') else None,
        cost=safe_decimal(request.form.get('cost')) if request.form.get('cost') else None
    )
    
    if success:
        try:
            # INTEGRITY: Synchronize invoice totals within the same transaction
            invoice = db.session.scalar(select(Invoice).filter_by(ticket_id=ticket_id))
            if invoice:
                invoice.calculate_total()
                if ticket.balance_due <= 0:
                    invoice.status = 'Paid'
                elif ticket.total_paid > 0:
                    invoice.status = 'Partial'
                else:
                    invoice.status = 'Unpaid'

            db.session.commit()
            flash(_('Part added.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Part addition error: {str(e)}")
            flash(_('Error saving part addition.'), 'error')
    else:
        flash(result, 'error')
        
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/payment/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('process_payments')
def record_payment(ticket_id):
    amount = safe_decimal(request.form.get('amount'))
    method = request.form.get('method')
    reference = request.form.get('reference', '').strip()

    ticket = db.session.get(Ticket, ticket_id)
    if not ticket or (not current_user.is_superuser and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'error')
        return redirect(url_for('main.dashboard'))

    if amount <= 0:
        flash(_('Payment amount must be greater than zero.'), 'error')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))
    
    success, result = FinancialService.record_payment(ticket_id, amount, method, reference, current_user.id)
    if success:
        try:
            db.session.flush() # Ensure payment is reflected in @property calculations
            # Update invoice status immediately following payment recording
            invoice = FinancialService.get_or_create_invoice(ticket_id)
            invoice.calculate_total()
            if ticket.balance_due <= 0:
                invoice.status = 'Paid'
            elif ticket.total_paid > 0:
                invoice.status = 'Partial'
            else:
                invoice.status = 'Unpaid'
            db.session.commit()
            flash(_('Payment recorded successfully.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Payment commit failed: {str(e)}")
            flash(_('An error occurred while recording the payment.'), 'error')
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
    
    payment = db.session.get(Payment, payment_id)
    if not payment or payment.ticket_id != ticket_id:
        flash(_('Invalid payment record.'), 'error')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    success, result = FinancialService.void_payment(payment_id, current_user.id)
    if success:
        try:
            db.session.flush() # Ensure property-based calculations are updated
            # INTEGRITY: Re-sync invoice status after payment removal
            invoice = db.session.scalar(select(Invoice).filter_by(ticket_id=ticket_id))
            if invoice:
                invoice.calculate_total()
                if ticket.balance_due > 0:
                    invoice.status = 'Partial' if ticket.total_paid > 0 else 'Unpaid'
                else:
                    invoice.status = 'Paid'
            db.session.commit()
            flash(result, 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Void payment error: {str(e)}")
            flash(_('Error voiding payment.'), 'error')
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
    
    # SECURITY/INTEGRITY: Verify the service belongs to this specific ticket
    item = db.session.get(InvoiceItem, ts_id)
    if not item or not item.invoice or item.invoice.ticket_id != ticket_id:
        flash(_('Invalid service selection for this ticket.'), 'error')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    success, result = InventoryService.remove_service(ticket_id, ts_id)
    if success:
        try:
            # INTEGRITY: Synchronize invoice totals within the same transaction
            invoice = db.session.scalar(select(Invoice).filter_by(ticket_id=ticket_id))
            if invoice:
                invoice.calculate_total()
                if ticket.balance_due <= 0:
                    invoice.status = 'Paid'
                elif ticket.total_paid > 0:
                    invoice.status = 'Partial'
                else:
                    invoice.status = 'Unpaid'

            db.session.commit()
            flash(_('Service removed.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Remove service error: {str(e)}")
            flash(_('Error removing service.'), 'error')
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

    # SECURITY/INTEGRITY: Verify the part belongs to this specific ticket
    item = db.session.get(InvoiceItem, item_id)
    if not item or not item.invoice or item.invoice.ticket_id != ticket_id:
        flash(_('Invalid part selection for this ticket.'), 'error')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    success, result = InventoryService.remove_part(item_id)
    if success:
        try:
            # INTEGRITY: Synchronize invoice totals within the same transaction
            invoice = db.session.scalar(select(Invoice).filter_by(ticket_id=ticket_id))
            if invoice:
                invoice.calculate_total()
                if ticket.balance_due <= 0:
                    invoice.status = 'Paid'
                elif ticket.total_paid > 0:
                    invoice.status = 'Partial'
                else:
                    invoice.status = 'Unpaid'

            db.session.commit()
            flash(_('Part removed and stock restored.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Remove part error: {str(e)}")
            flash(_('Error removing part.'), 'error')
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
        try:
            db.session.commit()
            flash(_('Ticket archived.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Archive error: {str(e)}")
            flash(_('Error archiving ticket.'), 'error')
        return redirect(url_for('ticket.tickets_list', view='history'))
    return redirect(url_for('main.dashboard'))

@ticket_bp.route('/delete/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('delete_ticket')
def delete_ticket(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    if ticket and (current_user.is_superuser or ticket.location_id == current_user.location_id):
        try:
            db.session.delete(ticket)
            db.session.commit()
            flash(_('Ticket permanently erased.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Delete error: {str(e)}")
            flash(_('Error deleting ticket. It may have linked records.'), 'error')
        return redirect(url_for('ticket.tickets_list'))
    
    flash(_('Ticket not found or access denied.'), 'error')
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
    invoice.calculate_total()
    if ticket.balance_due <= 0: # If balance is zero or negative, it's paid
        invoice.status = 'Paid'
    elif ticket.total_paid > 0:
        invoice.status = 'Partial'
    else:
        invoice.status = 'Unpaid'
    try:
        db.session.commit()
        flash(_('Invoice generated successfully.'), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Invoice creation failed: {str(e)}")
        flash(_('Error generating invoice.'), 'error')

    return redirect(url_for('ticket.view_invoice', ticket_id=ticket_id))