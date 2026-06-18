from datetime import datetime

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_babel import _
from flask_login import login_required, current_user
from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import joinedload, selectinload

from models import (CommonProblem, Customer, Device, Invoice, InvoiceItem,
                    Location, Note, Payment, PhaseLog, Role, Service,
                    SparePart, Ticket, TicketService, User, ShopSetting, db)
from services import (DocumentService, FinancialService, InventoryService,
                      RepairTicketService)
from .utils import require_permission, safe_decimal

ticket_bp = Blueprint('ticket', __name__)

@ticket_bp.route('/new', methods=['GET', 'POST'])
@login_required
@require_permission('create_ticket')
def new_ticket():
    is_admin = current_user.is_superuser or current_user.has_role('admin') # Define once
    loc_id = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))

    # Fetch shop settings for tax labels and regional configuration
    shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=loc_id))
    if not shop_info:
        shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=None))
    if not shop_info:
        shop_info = db.session.scalar(db.select(ShopSetting).limit(1))

    # Scoping common problems to the active location prevents data leakage between branches
    common_problems = db.session.scalars(db.select(CommonProblem).where(
        or_(CommonProblem.location_id == loc_id, CommonProblem.location_id == None),
        CommonProblem.is_active == True
    )).all()

    if is_admin:
        # UX: Admins/Superusers see all technicians to allow cross-branch ticket creation
        users = db.session.scalars(db.select(User).join(User.roles).where(
            User.is_active == True, Role.name == 'technician'
        ).order_by(User.full_name)).all()
    else:
        users = RepairTicketService.get_assignable_technicians(loc_id)

    now = datetime.now()

    if request.method == 'POST':
        customer_id = request.form.get('customer_id', type=int)
        device_id = request.form.get('device_id', type=int)
        items_included = request.form.get('items_included', '').strip()
        problem_description = request.form.get('problem_description', '').strip()

        # Validation: Ensure customer belongs to this location
        customer = db.session.get(Customer, customer_id)
        if not customer or (not is_admin and customer.location_id != current_user.location_id):
            flash(_('Invalid customer selection.'), 'danger')
        elif not (device := db.session.get(Device, device_id)):
            flash(_('Invalid device selection.'), 'danger')
        elif device.customer_id != customer_id:
            flash(_('Invalid device selection for this customer.'), 'danger')
        elif (dp := safe_decimal(request.form.get('down_payment', '0.00'))) < 0:
            flash(_('Down payment cannot be negative.'), 'danger')
        else:
            assigned_to = request.form.get('assigned_to', type=int) or None
            is_valid = True
            
            if assigned_to:
                tech = db.session.get(User, assigned_to)
                # Tech must be active and either a superuser or belong to the same branch as the customer (ticket destination)
                target_loc = customer.location_id
                if not tech or not tech.is_active or (not is_admin and not tech.is_superuser and tech.location_id != target_loc):
                    flash(_('Invalid technician assignment.'), 'danger')
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
                        flash(_('Invalid date or time format.'), 'danger')
                        return render_template('tickets/new_ticket.html', 
                                               common_problems=common_problems, users=users,
                                               shop_info=shop_info, # FIX: Pass shop_info on date/time error
                                               created_date=date_str, created_time=time_str,
                                               customer_id=customer_id, device_id=device_id,
                                               items_included=items_included, problem_description=problem_description,
                                               down_payment=request.form.get('down_payment'), payment_method=request.form.get('payment_method'),
                                               assigned_to=request.form.get('assigned_to', type=int),
                                               include_tax=request.form.get('include_tax') == 'on')

                try:
                    # SCALABILITY: Fallback to customer location if superuser is not assigned to a specific branch
                    ticket = RepairTicketService.create_ticket(
                        customer_id=customer_id,
                        device_id=device_id,
                        location_id=customer.location_id,
                        creator_id=current_user.id,
                        items_included=items_included,
                        problem_description=problem_description,
                        assigned_to=assigned_to,
                        created_at=created_at,
                        down_payment=dp,
                        payment_method=request.form.get('payment_method') or 'Cash', # Default to 'Cash' if not provided
                        include_tax=request.form.get('include_tax') == 'on'
                    )
                    db.session.commit()
                    flash(_('Ticket %(num)s created successfully!', num=ticket.ticket_number), 'success')
                    return redirect(url_for('ticket.view_ticket', ticket_id=ticket.id))
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Ticket creation failed: {str(e)}")
                    flash(_('An error occurred while creating the ticket.'), 'danger')

        # UX Integrity: Return form data on validation error to prevent data loss
        return render_template('tickets/new_ticket.html', 
                               common_problems=common_problems, 
                               users=users, 
                               shop_info=shop_info,
                               created_date=request.form.get('created_date', now.strftime('%Y-%m-%d')), 
                               created_time=request.form.get('created_time', now.strftime('%H:%M')),
                               customer_id=customer_id,
                               device_id=device_id,
                               items_included=items_included,
                               problem_description=problem_description,
                               down_payment=request.form.get('down_payment'),
                               payment_method=request.form.get('payment_method'),
                               assigned_to=request.form.get('assigned_to', type=int),
                               include_tax=request.form.get('include_tax') == 'on')
    
    return render_template('tickets/new_ticket.html', common_problems=common_problems, users=users, shop_info=shop_info)

@ticket_bp.route('/view/<int:ticket_id>')
@login_required
@require_permission('view_ticket')
def view_ticket(ticket_id):
    # Optimization: Eager load relations including audit logs and notes for the timeline UI
    stmt = db.select(Ticket).options(
        joinedload(Ticket.customer),
        joinedload(Ticket.device),
        joinedload(Ticket.creator),
        joinedload(Ticket.assigned_to_user),
        selectinload(Ticket.payments),
        selectinload(Ticket.phase_logs).joinedload(PhaseLog.technician_user),
        selectinload(Ticket.notes).joinedload(Note.author)
    ).where(Ticket.id == ticket_id)
    ticket = db.session.scalar(stmt)

    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        flash(_('Ticket not found'), 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Fetch shop settings for SKU visibility and tax info
    shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=ticket.location_id))
    if not shop_info: # Fallback to global settings if location-specific not found
        shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=None))
    if not shop_info:
        shop_info = db.session.scalar(db.select(ShopSetting).limit(1))

    # FIXED: Context-aware lookup for services and parts based on the ticket's branch
    # This allows global admins to see appropriate options for the specific location.
    services = db.session.scalars(db.select(Service).where(Service.location_id == ticket.location_id, Service.is_active == True)).all()
    parts = db.session.scalars(db.select(SparePart).where(SparePart.location_id == ticket.location_id, SparePart.is_active == True)).all()    
    return render_template('tickets/ticket_detail.html', ticket=ticket, services=services, parts=parts, shop_info=shop_info)

@ticket_bp.route('/list')
@login_required
@require_permission('view_ticket')
def tickets_list():
    """Comprehensive repository view for all branch tickets"""
    page = request.args.get('page', 1, type=int)
    view = request.args.get('view', 'active')
    search_query = request.args.get('q', '').strip()
    selected_location = request.args.get('location_id', type=int)
    
    filters = []

    # Multi-tenancy: Staff see their branch, superusers can filter or see all
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    locations = []
    if is_admin:
        locations = db.session.scalars(db.select(Location).order_by(Location.name)).all()
        if selected_location:
            filters.append(Ticket.location_id == selected_location)
    else:
        filters.append(Ticket.location_id == current_user.location_id)
    
    if view == 'history':
        # History view should include archived tickets
        filters.append(Ticket.current_phase.in_(['Already Taken', 'Cancelled']))
    else:
        # Active view should only show non-archived tickets
        filters.append(Ticket.is_archived.is_(False))
        filters.append(Ticket.current_phase.notin_(['Already Taken', 'Cancelled']))

    stmt = db.select(Ticket).options(
        joinedload(Ticket.customer), 
        joinedload(Ticket.device),
        joinedload(Ticket.creator),
        joinedload(Ticket.assigned_to_user),
        selectinload(Ticket.invoices)
    ).where(and_(*filters))

    if search_query:
        query_hash = Customer.get_search_hash(search_query)
        # INTEGRITY: Only compare against phone_hash if the query contains numeric digits
        search_filters = [
            Ticket.ticket_number.ilike(f'%{search_query}%'),
            Customer.name.ilike(f'%{search_query}%'),
            Device.brand.ilike(f'%{search_query}%'),
            Device.model_number.ilike(f'%{search_query}%'),
            Device.serial_number.ilike(f'%{search_query}%')
        ]
        if query_hash:
            search_filters.append(Customer.phone_hash == query_hash)
            
        stmt = stmt.join(Customer).join(Device).where(or_(*search_filters))

    stmt = stmt.order_by(desc(Ticket.created_at))
    
    tickets = db.paginate(stmt, page=page, per_page=20)
    return render_template('tickets/tickets_list.html', 
                           tickets=tickets, 
                           current_view=view, 
                           search_query=search_query, 
                           locations=locations, 
                           selected_location=selected_location)

@ticket_bp.route('/edit/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
@require_permission('edit_ticket')
def edit_ticket(ticket_id):
    """Allows correction of initial intake data"""
    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        flash(_('Ticket not found'), 'danger')
        return redirect(url_for('main.dashboard'))

    if ticket.current_phase == 'Already Taken' or ticket.is_archived:
        flash(_('This ticket is locked and cannot be modified.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket.id))
    
    # Fetch shop settings for tax label
    shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=ticket.location_id))
    if not shop_info: # Fallback to global settings if location-specific not found
        shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=None))
    if not shop_info:
        shop_info = db.session.scalar(db.select(ShopSetting).limit(1))
    if is_admin:
        # UX: Admins/Superusers see all technicians to allow cross-branch assignments
        users = db.session.scalars(db.select(User).join(User.roles).where(
            User.is_active == True, Role.name == 'technician'
        ).order_by(User.full_name)).all()
    else:
        users = RepairTicketService.get_assignable_technicians(ticket.location_id)

    if request.method == 'POST':
        new_items = request.form.get('items_included', '').strip()
        new_problem = request.form.get('problem_description', '').strip()
        new_assigned_to = request.form.get('assigned_to', type=int) or None

        # UX Integrity: Update object state before validation to ensure form retention on error
        ticket.items_included = new_items
        ticket.problem_description = new_problem
        ticket.assigned_to = new_assigned_to
        ticket.include_tax = request.form.get('include_tax') == 'on'
        
        if new_assigned_to:
            tech = db.session.get(User, new_assigned_to)
            if not tech or not tech.is_active or (not is_admin and not tech.is_superuser and tech.location_id != ticket.location_id):
                flash(_('Invalid technician assignment.'), 'danger')
                return render_template('tickets/edit_ticket.html', ticket=ticket, users=users, shop_info=shop_info)

        # Update Tax status and synchronize invoice
        invoice = db.session.scalar(db.select(Invoice).where(Invoice.ticket_id == ticket_id))
        if invoice:
            invoice.include_tax = ticket.include_tax
            invoice.calculate_total()
            db.session.flush()
            # Sync payment status in case totals changed due to tax edit
            FinancialService.sync_invoice_status(invoice.id)

        try:
            db.session.commit()
            flash(_('Ticket intake data updated successfully.'), 'success')
            return redirect(url_for('ticket.view_ticket', ticket_id=ticket.id))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Ticket edit failed: {str(e)}")
            flash(_('Error updating ticket data.'), 'danger')
            return render_template('tickets/edit_ticket.html', ticket=ticket, users=users, shop_info=shop_info)

    return render_template('tickets/edit_ticket.html', ticket=ticket, users=users, shop_info=shop_info)

@ticket_bp.route('/toggle_tax/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('edit_ticket')
def toggle_tax(ticket_id):
    """AJAX toggle for ticket tax inclusion"""
    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        return jsonify({'success': False, 'message': _('Access denied')}), 403
    
    # INTEGRITY: Prevent modification of historical/locked documents
    if ticket.is_archived or ticket.current_phase == 'Already Taken':
        return jsonify({'success': False, 'message': _('Cannot modify an archived ticket.')}), 400

    # UX Integrity: Ensure data is subscriptable
    data = request.get_json() or {}
    ticket.include_tax = data.get('include_tax', True)
    
    # INTEGRITY: Ensure invoice exists and is synchronized within the transaction
    invoice = FinancialService.get_or_create_invoice(ticket.id)
    invoice.include_tax = ticket.include_tax
    invoice.calculate_total()
    FinancialService.sync_invoice_status(invoice.id)
    
    try:
        db.session.commit()
        return jsonify(FinancialService.get_invoice_summary_json(invoice)) # Return full summary
    except Exception as e:
        current_app.logger.error(f"Tax toggle failed: {str(e)}")
        return jsonify({'success': False, 'message': _('An error occurred while toggling tax.')}), 500

@ticket_bp.route('/summary/<int:ticket_id>', methods=['GET'])
@login_required
@require_permission('view_ticket')
def get_summary(ticket_id):
    """AJAX endpoint to get the latest financial summary for a ticket"""
    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        return jsonify({'success': False, 'message': _('Access denied')}), 403
    
    invoice = FinancialService.get_or_create_invoice(ticket.id) # Ensure invoice exists
    
    try:
        db.session.commit() # INTEGRITY: Persist the invoice record if it was newly created
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Summary persistence failed: {str(e)}")
        return jsonify({'success': False, 'message': _('Failed to update financial summary.')}), 500

    return jsonify(FinancialService.get_invoice_summary_json(invoice))

@ticket_bp.route('/update_phase/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('update_phase')
def update_phase(ticket_id):
    new_phase = request.form.get('phase')
    commentary = request.form.get('commentary', '').strip()

    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'danger')
        return redirect(url_for('main.dashboard'))
    
    try:
        success, result = RepairTicketService.update_phase(ticket_id, new_phase, current_user.id, commentary)
        if success:
            # SAFETY: Ensure that changing phase to 'Already Taken' does not automatically archive the ticket.
            # Archiving must remain a separate, manual step to preserve the distinction between 
            # "work finished/picked up" and "moved to long-term storage".
            # INTEGRITY: Ensure invoice exists and is synchronized after phase change
            invoice = FinancialService.get_or_create_invoice(ticket.id)
            FinancialService.sync_invoice_status(invoice.id)
            db.session.commit()
            flash(_('Ticket status updated to %(phase)s', phase=_(new_phase)), 'success')
        else:
            flash(result, 'danger')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Phase update error: {str(e)}")
        flash(_('An unexpected error occurred during status update.'), 'danger')
        
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/invoice/<int:ticket_id>')
@login_required
@require_permission('view_ticket')
def view_invoice(ticket_id):
    """Renders the HTML version of the invoice for viewing/printing"""
    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        flash(_('Ticket not found'), 'danger')
        return redirect(url_for('main.dashboard'))
    
    # Ensure an invoice record exists for the ticket and get its ID
    invoice = FinancialService.get_or_create_invoice(ticket_id)

    # INTEGRITY: Always recalculate and sync status for active/unpaid invoices
    # Fix: Prevent recalculation for locked/archived tickets to preserve historical VAT/pricing integrity
    if (invoice.status != 'Paid' or ticket.balance_due != 0) and ticket.current_phase != 'Already Taken' and not ticket.is_archived:
        try:
            invoice.calculate_total()
            db.session.flush() # Ensure the total change is visible to ticket.balance_due
            FinancialService.sync_invoice_status(invoice.id)
            db.session.commit()
            db.session.refresh(invoice)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Invoice status sync failed: {str(e)}")
    
    # INTEGRITY: Fetch shop settings for branding and document labels specific to the ticket's branch
    shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=ticket.location_id))
    if not shop_info:
        shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=None))
    if not shop_info:
        shop_info = db.session.scalar(db.select(ShopSetting).limit(1))

    return render_template('tickets/invoice.html', invoice=invoice, shop_info=shop_info)

@ticket_bp.route('/invoice/download/<int:ticket_id>')
@login_required
@require_permission('view_ticket')
def download_invoice_pdf(ticket_id):
    """Triggers the DocumentService to generate and stream a PDF invoice"""
    doc_type = request.args.get('type', 'invoice')
    # SECURITY: Validate document type to prevent unexpected service behavior
    if doc_type not in ['invoice', 'receipt', 'job_sheet']:
        doc_type = 'invoice'
        
    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        flash(_('Ticket not found'), 'danger')
        return redirect(url_for('main.dashboard'))

    invoice = FinancialService.get_or_create_invoice(ticket_id) # Ensure invoice exists
    try:
        db.session.commit() # INTEGRITY: Ensure the invoice context is persisted before generating the PDF
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Invoice persistence for PDF failed: {str(e)}")
        flash(_('Error preparing document.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    success, result = DocumentService.generate_invoice_pdf(invoice.id, doc_type=doc_type)
    if success:
        return send_file(
            result,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"{doc_type}_{ticket.ticket_number}.pdf"
        )
    flash(result, 'danger')
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/add_service/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('add_service')
def add_service(ticket_id):
    service_id = request.form.get('service_id', type=int)
    quantity = request.form.get('quantity', 1, type=int)

    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'danger')
        return redirect(url_for('main.dashboard'))

    if ticket.current_phase == 'Already Taken' or ticket.is_archived:
        flash(_('This ticket is locked and cannot be modified.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    if not service_id:
        flash(_('Please select a service.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    if quantity < 1:
        flash(_('Quantity must be at least 1.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))
    
    service = db.session.get(Service, service_id)
    if not service or service.location_id != ticket.location_id:
        flash(_('Invalid service selection.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    success, result = InventoryService.add_service_to_ticket(ticket_id, service_id, quantity)
    if success:
        try:
            # INTEGRITY: Synchronize invoice totals within the same transaction
            invoice = FinancialService.get_or_create_invoice(ticket.id)
            if ticket.current_phase != 'Already Taken' and not ticket.is_archived:
                invoice.calculate_total()
                db.session.flush() # Ensure the total change is visible to ticket.balance_due
                FinancialService.sync_invoice_status(invoice.id)

            db.session.commit()
            flash(_('Service added.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Service addition error: {str(e)}")
            flash(_('Error saving service addition.'), 'danger')
    else:
        flash(result, 'danger')
        
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/add_part/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('add_part')
def add_part(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'danger')
        return redirect(url_for('main.dashboard'))

    if ticket.current_phase == 'Already Taken' or ticket.is_archived:
        flash(_('This ticket is locked and cannot be modified.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    quantity = request.form.get('quantity', 1, type=int)
    if quantity < 1:
        flash(_('Quantity must be at least 1.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    if not request.form.get('part_id') and not request.form.get('manual_name', '').strip():
        flash(_('Please select a part or enter a manual description.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    part_id = request.form.get('part_id', type=int)
    if part_id:
        part = db.session.get(SparePart, part_id)
        if not part or part.location_id != ticket.location_id:
            flash(_('Invalid part selection.'), 'danger')
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
            invoice = FinancialService.get_or_create_invoice(ticket.id)
            if ticket.current_phase != 'Already Taken' and not ticket.is_archived:
                invoice.calculate_total()
                db.session.flush() # Ensure the total change is visible to ticket.balance_due
                FinancialService.sync_invoice_status(invoice.id)

            db.session.commit()
            flash(_('Part added.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Part addition error: {str(e)}")
            flash(_('Error saving part addition.'), 'danger')
    else:
        flash(result, 'danger')
        
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/payment/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('process_payments')
def record_payment(ticket_id):
    amount = safe_decimal(request.form.get('amount'))
    method = request.form.get('method')
    reference = request.form.get('reference', '').strip()

    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'danger')
        return redirect(url_for('main.dashboard'))

    if ticket.is_archived or ticket.current_phase == 'Already Taken':
        flash(_('Cannot record payments for an archived ticket.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    if amount <= 0:
        flash(_('Payment amount must be greater than zero.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))
    
    # If the ticket has a negative balance due, we are returning/refunding money.
    # Therefore, the amount recorded should be negated.
    if ticket.balance_due < 0:
        amount = -abs(amount)

    # INTEGRITY: Ensure an invoice exists before recording a payment against it
    invoice = FinancialService.get_or_create_invoice(ticket_id)
    success, result = FinancialService.record_payment(invoice.id, amount, method, reference, current_user.id)

    if success:
        try:
            db.session.flush() # Ensure payment is reflected in @property calculations
            if ticket.current_phase != 'Already Taken' and not ticket.is_archived:
                invoice.calculate_total()
            db.session.flush() # Ensure the total change is visible to ticket.balance_due
            FinancialService.sync_invoice_status(invoice.id)
            db.session.commit()
            flash(_('Payment recorded successfully.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Payment commit failed: {str(e)}")
            flash(_('An error occurred while recording the payment.'), 'danger')
    else:
        flash(result, 'danger')
        
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/payment/void/<int:ticket_id>/<int:payment_id>', methods=['POST'])
@login_required
@require_permission('process_payments')
def void_payment(ticket_id, payment_id):
    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'danger')
        return redirect(url_for('main.dashboard'))
    
    if ticket.is_archived or ticket.current_phase == 'Already Taken':
        flash(_('Cannot void payments for an archived ticket.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    payment = db.session.get(Payment, payment_id)
    if not payment or payment.ticket_id != ticket_id:
        flash(_('Invalid payment record.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    success, result = FinancialService.void_payment(payment_id, current_user.id)
    if success:
        try:
            db.session.flush() # Ensure property-based calculations are updated
            # INTEGRITY: Ensure invoice exists and is synchronized after payment removal
            invoice = FinancialService.get_or_create_invoice(ticket.id)
            if ticket.current_phase != 'Already Taken' and not ticket.is_archived:
                invoice.calculate_total()
                db.session.flush() # Ensure the total change is visible to ticket.balance_due
                FinancialService.sync_invoice_status(invoice.id)
            db.session.commit()
            flash(result, 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Void payment error: {str(e)}")
            flash(_('Error voiding payment.'), 'danger')
    else:
        flash(result, 'danger')
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/remove_service/<int:ticket_id>/<int:ts_id>', methods=['POST'])
@login_required
@require_permission('remove_service')
def remove_service(ticket_id, ts_id):
    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'danger')
        return redirect(url_for('main.dashboard'))
    
    if ticket.current_phase == 'Already Taken' or ticket.is_archived:
        flash(_('This ticket is locked and cannot be modified.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    # SECURITY/INTEGRITY: Verify the service belongs to this specific ticket
    ts = db.session.get(TicketService, ts_id)
    if not ts or ts.ticket_id != ticket_id:
        flash(_('Invalid service selection for this ticket.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    success, result = InventoryService.remove_service(ticket_id, ts_id)
    if success:
        try:
            # INTEGRITY: Synchronize invoice totals within the same transaction
            invoice = FinancialService.get_or_create_invoice(ticket.id)
            if ticket.current_phase != 'Already Taken' and not ticket.is_archived:
                invoice.calculate_total()
                db.session.flush() # Ensure the total change is visible to ticket.balance_due
                FinancialService.sync_invoice_status(invoice.id)

            db.session.commit()
            flash(_('Service removed.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Remove service error: {str(e)}")
            flash(_('Error removing service.'), 'danger')
    else:
        flash(result, 'danger')
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/remove_part/<int:ticket_id>/<int:item_id>', methods=['POST'])
@login_required
@require_permission('remove_part')
def remove_part(ticket_id, item_id):
    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        flash(_('Access denied or ticket not found.'), 'danger')
        return redirect(url_for('main.dashboard'))

    if ticket.current_phase == 'Already Taken' or ticket.is_archived:
        flash(_('This ticket is locked and cannot be modified.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    # SECURITY/INTEGRITY: Verify the part belongs to this specific ticket
    item = db.session.get(InvoiceItem, item_id)
    if not item or not item.invoice or item.invoice.ticket_id != ticket_id:
        flash(_('Invalid part selection for this ticket.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

    success, result = InventoryService.remove_part(item_id)
    if success:
        try:
            # INTEGRITY: Synchronize invoice totals within the same transaction
            invoice = FinancialService.get_or_create_invoice(ticket.id)
            if ticket.current_phase != 'Already Taken' and not ticket.is_archived:
                invoice.calculate_total()
                db.session.flush() # Ensure the total change is visible to ticket.balance_due
                FinancialService.sync_invoice_status(invoice.id)

            db.session.commit()
            flash(_('Part removed and stock restored.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Remove part error: {str(e)}")
            flash(_('Error removing part.'), 'danger')
    else:
        flash(result, 'danger')
    return redirect(url_for('ticket.view_ticket', ticket_id=ticket_id))

@ticket_bp.route('/archive/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
@require_permission('archive_ticket')
def archive_ticket(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        flash(_('Ticket not found or access denied.'), 'danger')
        return redirect(url_for('main.dashboard'))

    if ticket.current_phase not in ['Already Taken', 'Cancelled']:
        flash(_('Only tickets that have been picked up or cancelled can be archived.'), 'danger')
        return redirect(url_for('ticket.view_ticket', ticket_id=ticket.id))

    if request.method == 'POST':
        # Integrity: Lock in totals one last time before archiving
        # INTEGRITY: Ensure invoice exists and is synchronized before archiving
        invoice = FinancialService.get_or_create_invoice(ticket.id)
        invoice.calculate_total()
        ticket.is_archived = True
        try:
            db.session.commit()
            flash(_('Ticket archived.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Archive error: {str(e)}")
            flash(_('Error archiving ticket.'), 'danger')
        return redirect(url_for('ticket.tickets_list', view='history'))

    return render_template('tickets/archive_ticket.html', ticket=ticket)

@ticket_bp.route('/delete/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('delete_ticket')
def delete_ticket(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if ticket and (is_admin or ticket.location_id == current_user.location_id):
        # INTEGRITY: Do not allow deleting tickets with recorded payments.
        # This preserves financial audit trails. Void payments first if needed.
        if ticket.total_paid > 0:
            flash(_('Cannot delete a ticket with recorded payments. Void payments first.'), 'danger')
            return redirect(url_for('ticket.view_ticket', ticket_id=ticket.id))
        try:
            db.session.delete(ticket)
            db.session.commit()
            flash(_('Ticket permanently erased.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Delete error: {str(e)}")
            flash(_('Error deleting ticket. It may have linked records.'), 'danger')
        return redirect(url_for('ticket.tickets_list'))
    
    flash(_('Ticket not found or access denied.'), 'danger')
    return redirect(url_for('main.dashboard'))

@ticket_bp.route('/invoice/create/<int:ticket_id>', methods=['POST'])
@login_required
@require_permission('create_invoice')
def create_invoice(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not ticket or (not is_admin and ticket.location_id != current_user.location_id):
        flash(_('Ticket not found'), 'danger')
        return redirect(url_for('main.dashboard'))
    
    invoice = FinancialService.get_or_create_invoice(ticket_id)
    if ticket.current_phase != 'Already Taken' and not ticket.is_archived:
        invoice.calculate_total()
    db.session.flush() # Ensure the total change is visible to ticket.balance_due
    FinancialService.sync_invoice_status(invoice.id)
    try:
        db.session.commit()
        flash(_('Invoice generated successfully.'), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Invoice creation failed: {str(e)}")
        flash(_('Error generating invoice.'), 'danger')

    return redirect(url_for('ticket.view_invoice', ticket_id=ticket_id))