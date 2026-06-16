from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy import desc
from sqlalchemy.orm import joinedload

from models import Customer, Invoice, InvoiceItem, Location, Service, SparePart, Ticket, TicketService, db
from services.core import FinancialService, InventoryService
from .utils import require_permission, safe_decimal

pos_bp = Blueprint('pos', __name__)

@pos_bp.route('/')
@login_required
@require_permission('process_sales')
def index():
    """Main POS interface listing parts and services"""
    selected_location = request.args.get('location_id', type=int)
    page_s = request.args.get('page_s', 1, type=int)
    page_p = request.args.get('page_p', 1, type=int)

    locations = []
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if is_admin:
        # Discover all locations for the branch switcher
        locations = db.session.scalars(db.select(Location).order_by(Location.name)).all()
        loc_id = selected_location or current_user.location_id or (locations[0].id if locations else None)
    else:
        loc_id = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    
    services_query = db.select(Service).where(Service.is_active == True, Service.location_id == loc_id).order_by(Service.name)
    services = db.paginate(services_query, page=page_s, per_page=10)

    parts_query = db.select(SparePart).where(SparePart.stock_quantity > 0, SparePart.location_id == loc_id).order_by(SparePart.name)
    parts = db.paginate(parts_query, page=page_p, per_page=10)
    
    # Show customers for the active location
    # Privacy: Hide anonymized/deleted users from POS selection by default
    cust_stmt = db.select(Customer).where(
        (Customer.location_id == loc_id) & 
        (Customer.is_anonymized.is_(False)) & 
        (~Customer.name.ilike('DELETED_USER_%'))
    ).limit(50)
    customers = db.session.scalars(cust_stmt).all()
    
    return render_template('pos/index.html', 
                           services=services, 
                           parts=parts, 
                           customers=customers, 
                           locations=locations, 
                           selected_location=loc_id)

@pos_bp.route('/history')
@login_required
@require_permission('process_sales')
def history():
    """Lists all past sales and invoices for the branch"""
    page = request.args.get('page', 1, type=int)
    selected_location = request.args.get('location_id', type=int)
    loc_id = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    
    stmt = db.select(Invoice).options(
        joinedload(Invoice.customer),
        joinedload(Invoice.ticket).joinedload(Ticket.customer)
    ).order_by(desc(Invoice.created_at))
    
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    locations = []
    if not is_admin:
        stmt = stmt.where(Invoice.location_id == loc_id)
    else:
        locations = db.session.scalars(db.select(Location).order_by(Location.name)).all()
        if selected_location:
            stmt = stmt.where(Invoice.location_id == selected_location)

    invoices = db.paginate(stmt, page=page, per_page=20)
    return render_template('pos/history.html', 
                           invoices=invoices, 
                           locations=locations, 
                           selected_location=selected_location)

@pos_bp.route('/create_sale', methods=['POST'])
@login_required
@require_permission('process_sales')
def create_sale():
    """Initializes a standalone invoice for a direct sale"""
    customer_id = request.form.get('customer_id', type=int)
    selected_location = request.form.get('location_id', type=int)
    
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    # Ensure the invoice is tied to the user's branch or a fallback
    if is_admin and selected_location:
        loc_id = selected_location
    else:
        loc_id = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    
    if customer_id:
        customer = db.session.get(Customer, customer_id)
        is_admin = current_user.is_superuser or current_user.has_role('admin')
        if not customer or customer.is_anonymized or (not is_admin and customer.location_id != loc_id):
            flash(_('Invalid customer selection.'), 'danger')
            return redirect(url_for('pos.index'))

    try:
        invoice = FinancialService.get_or_create_invoice(
            customer_id=customer_id, 
            location_id=loc_id
        )
        db.session.commit()
        return redirect(url_for('pos.cart', invoice_id=invoice.id))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"POS sale creation failed: {str(e)}")
        flash(_('Failed to create sale.'), 'danger')
        return redirect(url_for('pos.index'))

@pos_bp.route('/cart/<int:invoice_id>')
@login_required
@require_permission('process_sales')
def cart(invoice_id):
    """Displays the active sale cart; allowed if not fully paid"""
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        flash(_('Sale not found.'), 'danger')
        return redirect(url_for('pos.index'))
    
    # Security: Ensure POS invoices belong to the user's location or the default branch
    # Superusers bypass this check to allow global management
    # Consistency: Use the same fallback logic here as in index/create_sale
    effective_loc = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    
    if not is_admin and invoice.location_id != effective_loc:
        flash(_('Access denied.'), 'danger')
        return redirect(url_for('pos.index'))
    
    # Use the invoice location as the primary source for parts/services lookup
    loc_id = invoice.location_id or current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    services = db.session.scalars(db.select(Service).where(Service.is_active == True, Service.location_id == loc_id)).all()
    parts = db.session.scalars(db.select(SparePart).where(SparePart.stock_quantity > 0, SparePart.location_id == loc_id)).all()
    return render_template('pos/cart.html', invoice=invoice, services=services, parts=parts)

@pos_bp.route('/add_item/<int:invoice_id>', methods=['POST'])
@login_required
@require_permission('process_sales')
def add_item(invoice_id):
    """Adds a service or part to the POS invoice"""
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        flash(_('Sale not found.'), 'danger')
        return redirect(url_for('pos.index'))

    # Security: Multi-tenancy check
    effective_loc = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not is_admin and invoice.location_id != effective_loc:
        flash(_('Access denied.'), 'danger')
        return redirect(url_for('pos.index'))

    if invoice.status == 'Paid':
        flash(_('Cannot add items to a completed sale.'), 'danger')
        return redirect(url_for('pos.cart', invoice_id=invoice_id))

    item_type = request.form.get('type')
    item_id = request.form.get('id', type=int)
    quantity = request.form.get('quantity', type=int, default=1)

    if not item_id:
        flash(_('Please select an item.'), 'danger')
        return redirect(url_for('pos.cart', invoice_id=invoice_id))

    if quantity < 1:
        flash(_('Quantity must be at least 1.'), 'danger')
        return redirect(url_for('pos.cart', invoice_id=invoice_id))

    try:
        if item_type == 'service':
            success, msg = InventoryService.add_service_to_invoice(invoice_id, item_id, quantity)
        elif item_type == 'part':
            success, msg = InventoryService.add_part_to_invoice(invoice_id, item_id, None, quantity, None, None)
        else:
            flash(_('Invalid item type.'), 'danger')
            return redirect(url_for('pos.cart', invoice_id=invoice_id))

        if not success:
            flash(msg, 'danger')
        else:
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"POS item addition failed: {str(e)}")
        flash(_('An error occurred while adding the item.'), 'danger')
    
    return redirect(url_for('pos.cart', invoice_id=invoice_id))

@pos_bp.route('/checkout/<int:invoice_id>', methods=['POST'])
@login_required
@require_permission('process_sales')
def checkout(invoice_id):
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        flash(_('Sale not found.'), 'danger')
        return redirect(url_for('pos.index'))

    # Security: Multi-tenancy check
    effective_loc = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not is_admin and invoice.location_id != effective_loc:
        flash(_('Access denied.'), 'danger')
        return redirect(url_for('pos.index'))

    if invoice.status == 'Paid':
        flash(_('This sale has already been completed.'), 'info')
        return redirect(url_for('pos.index'))

    amount = safe_decimal(request.form.get('amount'))
    method = request.form.get('method', default='Cash')
    reference = request.form.get('reference', default='')

    if amount <= 0:
        flash(_('Invalid payment amount.'), 'danger')
        return redirect(url_for('pos.cart', invoice_id=invoice_id))

    try:
        success, result = FinancialService.record_payment(
            invoice_id=invoice_id,
            amount=amount,
            method=method,
            reference=reference,
            user_id=current_user.id
        )

        if success:
            db.session.commit()
            flash(_('Sale completed successfully!'), 'success')
            return redirect(url_for('pos.index'))
        else:
            flash(result, 'danger')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"POS checkout error: {str(e)}")
        flash(_('An error occurred during checkout.'), 'danger')
    
    return redirect(url_for('pos.cart', invoice_id=invoice_id))

@pos_bp.route('/remove_item/<int:invoice_id>/<int:item_id>', methods=['POST'])
@login_required
@require_permission('process_sales')
def remove_item(invoice_id, item_id):
    """Removes an item (part or standalone service) from the invoice"""
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        flash(_('Sale not found.'), 'danger')
        return redirect(url_for('pos.index'))

    if invoice.status == 'Paid':
        flash(_('Cannot modify a completed sale.'), 'danger')
        return redirect(url_for('pos.cart', invoice_id=invoice_id))

    # Security: Ensure POS invoices belong to the user's location
    effective_loc = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not is_admin and invoice.location_id != effective_loc:
        flash(_('Access denied.'), 'danger')
        return redirect(url_for('pos.index'))

    item = db.session.get(InvoiceItem, item_id)
    if not item or item.invoice_id != invoice_id:
        flash(_('Item not found in this sale.'), 'danger')
        return redirect(url_for('pos.cart', invoice_id=invoice_id))

    try:
        success, msg = InventoryService.remove_part(item_id)
        if success:
            db.session.commit()
            flash(_('Item removed.'), 'success')
        else:
            flash(msg, 'danger')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"POS item removal failed: {str(e)}")
        flash(_('An error occurred while removing the item.'), 'danger')
    
    return redirect(url_for('pos.cart', invoice_id=invoice_id))

@pos_bp.route('/remove_service/<int:invoice_id>/<int:ts_id>', methods=['POST'])
@login_required
@require_permission('process_sales')
def remove_service(invoice_id, ts_id):
    """Removes a ticket-linked service from the invoice"""
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        flash(_('Sale not found.'), 'danger')
        return redirect(url_for('pos.index'))

    if not invoice.ticket_id or invoice.status == 'Paid':
        flash(_('Invalid request. Only ticket-linked services can be removed here.'), 'danger')
        return redirect(url_for('pos.cart', invoice_id=invoice_id))

    # Security check
    effective_loc = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not is_admin and invoice.location_id != effective_loc:
        flash(_('Access denied.'), 'danger')
        return redirect(url_for('pos.index'))

    # SECURITY/INTEGRITY: Verify the service belongs to this specific sale context
    ts = db.session.get(TicketService, ts_id)
    if not ts or ts.ticket_id != invoice.ticket_id:
        flash(_('Invalid service selection for this sale.'), 'danger')
        return redirect(url_for('pos.cart', invoice_id=invoice_id))

    try:
        success, msg = InventoryService.remove_service(invoice.ticket_id, ts_id)
        if success:
            db.session.commit()
            flash(_('Service removed.'), 'success')
        else:
            flash(msg, 'danger')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"POS service removal failed: {str(e)}")
        flash(_('An error occurred while removing the service.'), 'danger')
    
    return redirect(url_for('pos.cart', invoice_id=invoice_id))

@pos_bp.route('/delete/<int:invoice_id>', methods=['POST'])
@login_required
@require_permission('process_sales')
def delete_sale(invoice_id):
    """Permanently removes a draft POS sale and restores stock"""
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        flash(_('Sale not found.'), 'danger')
        return redirect(url_for('pos.history'))
    
    # Integrity: Only allow erasing standalone POS sales (not repair invoices)
    if invoice.ticket_id:
        flash(_('Invalid request. Only standalone POS sales can be erased.'), 'danger')
        return redirect(url_for('pos.history'))

    # Security: Multi-tenancy check
    effective_loc = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not is_admin and invoice.location_id != effective_loc:
        flash(_('Access denied.'), 'danger')
        return redirect(url_for('pos.history'))

    # Safety: Do not allow deleting if money has already changed hands
    if invoice.full_payment_received > 0:
        flash(_('Cannot erase a sale with recorded payments. Void payments first.'), 'danger')
        return redirect(url_for('pos.history'))

    try:
        # Inventory Integrity: Restore stock for all parts in this cart before deleting
        for item in list(invoice.items):
            if item.spare_part_id:
                success, msg = InventoryService.remove_part(item.id)
                if not success:
                    raise Exception(msg or f"Failed to restore stock for item ID {item.id}")
        
        db.session.delete(invoice)
        db.session.commit()
        flash(_('Draft sale erased successfully.'), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Sale deletion failed: {str(e)}")
        flash(_('Error erasing sale.'), 'danger')

    return redirect(url_for('pos.history'))

@pos_bp.route('/add_by_sku/<int:invoice_id>', methods=['POST'])
@login_required
@require_permission('process_sales')
def add_by_sku(invoice_id):
    """Quickly adds a part to the cart by scanning a SKU/Barcode"""
    sku = request.form.get('sku', '').strip().upper()
    if not sku:
        return redirect(url_for('pos.cart', invoice_id=invoice_id))

    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        flash(_('Sale not found.'), 'danger')
        return redirect(url_for('pos.index'))

    if invoice.status == 'Paid':
        flash(_('Cannot add items to a completed sale.'), 'danger')
        return redirect(url_for('pos.cart', invoice_id=invoice_id))

    # Security: Multi-tenancy check
    effective_loc = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not is_admin and invoice.location_id != effective_loc:
        flash(_('Access denied.'), 'danger')
        return redirect(url_for('pos.index'))

    # Find part by SKU at this specific location
    part = db.session.scalar(db.select(SparePart).where(SparePart.sku == sku, SparePart.location_id == invoice.location_id))
    
    if not part:
        flash(_('No part found with SKU: %(sku)s', sku=sku), 'danger')
    else:
        try:
            success, msg = InventoryService.add_part_to_invoice(invoice_id, part.id, None, 1, None, None)
            if success:
                db.session.commit()
                flash(_('%(name)s added to cart.', name=part.name), 'success')
            else:
                flash(msg, 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"SKU addition failed: {str(e)}")
            flash(_('An error occurred while adding the part.'), 'danger')

    return redirect(url_for('pos.cart', invoice_id=invoice_id))