from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for, send_file
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy import desc
from sqlalchemy.orm import joinedload

from models import (Customer, Invoice, InvoiceItem, Location, Service,
                    ShopSetting, SparePart, Ticket, TicketService, db)
from services.core import FinancialService, InventoryService, DocumentService
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
    
    # Fetch shop settings for SKU visibility and tax info
    shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=loc_id))
    if not shop_info: # Fallback to global settings if location-specific not found
        shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=None))
    if not shop_info:
        shop_info = db.session.scalar(db.select(ShopSetting).limit(1))

    services = db.session.scalars(db.select(Service).where(Service.is_active == True, Service.location_id == loc_id)).all()
    parts = db.session.scalars(db.select(SparePart).where(SparePart.stock_quantity > 0, SparePart.location_id == loc_id)).all()
    return render_template('pos/cart.html', invoice=invoice, services=services, parts=parts, shop_info=shop_info)

@pos_bp.route('/update_item_details/<int:invoice_id>/<int:item_id>', methods=['POST'])
@login_required
@require_permission('process_sales')
def update_item_details(invoice_id, item_id):
    """Updates quantity or price for an existing item in the cart"""
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice or invoice.status == 'Paid':
        flash(_('Sale not found or already completed.'), 'danger')
        return redirect(url_for('pos.index'))

    # Security: Multi-tenancy check
    effective_loc = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    if not (current_user.is_superuser or current_user.has_role('admin')) and invoice.location_id != effective_loc:
        flash(_('Access denied.'), 'danger')
        return redirect(url_for('pos.index'))

    item = db.session.get(InvoiceItem, item_id)
    if not item or item.invoice_id != invoice_id:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': _('Item not found.')}), 404
        flash(_('Item not found.'), 'danger')
        return redirect(url_for('pos.cart', invoice_id=invoice_id))

    # UX Integrity: Ensure data is subscriptable even if JSON parsing fails or returns None
    data = (request.get_json() if request.is_json else request.form) or {}
    new_qty = data.get('quantity')
    if new_qty is not None:
        try:
            new_qty = int(new_qty)
        except (ValueError, TypeError):
            new_qty = None
            
    new_price = safe_decimal(data.get('unit_price')) if data.get('unit_price') is not None else None

    try:
        if new_qty is not None and new_qty > 0:
            # If it's a part, we need to handle stock delta
            if item.spare_part_id:
                delta = new_qty - item.quantity
                part = db.session.get(SparePart, item.spare_part_id)
                if part.stock_quantity < delta:
                    msg = _('Insufficient stock to increase quantity.')
                    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return jsonify({'success': False, 'message': msg}), 400
                    flash(msg, 'danger')
                    return redirect(url_for('pos.cart', invoice_id=invoice_id))
                part.stock_quantity -= delta
            item.quantity = new_qty

        if new_price is not None and new_price >= 0:
            item.unit_price = new_price

        item.total_price = item.unit_price * item.quantity
        invoice.calculate_total()
        FinancialService.sync_invoice_status(invoice.id)
        db.session.commit()
        return jsonify(FinancialService.get_invoice_summary_json(invoice))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Cart update failed: {str(e)}")
        # Return JSON error for AJAX
        return jsonify({'success': False, 'message': _('Failed to update item.')}), 500


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

@pos_bp.route('/toggle_tax/<int:invoice_id>', methods=['POST'])
@login_required
@require_permission('process_sales')
def toggle_tax(invoice_id):
    """Toggles tax inclusion for an invoice and recalculates totals."""
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        return jsonify({'success': False, 'message': _('Invoice not found.')}), 404

    # Security: Multi-tenancy check
    effective_loc = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not is_admin and invoice.location_id != effective_loc:
        return jsonify({'success': False, 'message': _('Access denied.')}), 403

    if invoice.status == 'Paid':
        return jsonify({'success': False, 'message': _('Cannot modify a completed sale.')}), 400

    data = request.get_json() or {}
    new_include_tax = data.get('include_tax', False)

    try:
        invoice.include_tax = new_include_tax
        invoice.calculate_total()
        FinancialService.sync_invoice_status(invoice.id)
        db.session.commit()
        return jsonify(FinancialService.get_invoice_summary_json(invoice))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Toggle tax failed: {str(e)}")
        return jsonify({'success': False, 'message': _('System error')}), 500

@pos_bp.route('/update_discount/<int:invoice_id>', methods=['POST'])
@login_required
@require_permission('process_sales')
def update_discount(invoice_id):
    """Updates the global discount for an invoice via AJAX"""
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice or invoice.status == 'Paid':
        return jsonify({'success': False, 'message': _('Sale not found or completed.')}), 404

    # Security: Multi-tenancy check
    effective_loc = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not is_admin and invoice.location_id != effective_loc:
        return jsonify({'success': False, 'message': _('Access denied.')}), 403

    data = (request.get_json() if request.is_json else request.form) or {}
    discount_amount = safe_decimal(data.get('discount_amount', '0'))
    discount_type = data.get('discount_type', 'fixed')

    try:
        invoice.discount_amount = discount_amount
        invoice.discount_type = discount_type
        invoice.calculate_total()
        FinancialService.sync_invoice_status(invoice.id) # Ensure status is updated after discount
        db.session.commit()
        return jsonify(FinancialService.get_invoice_summary_json(invoice))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Discount update failed: {str(e)}")
        return jsonify({'success': False, 'message': _('Update failed')}), 500

@pos_bp.route('/redeem_loyalty/<int:invoice_id>', methods=['POST'])
@login_required
@require_permission('process_sales')
def redeem_loyalty(invoice_id):
    """Redeems loyalty points via AJAX"""
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice or invoice.status == 'Paid' or not invoice.customer:
        return jsonify({'success': False, 'message': _('Redemption unavailable.')}), 400

    # Security: Multi-tenancy check
    effective_loc = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not is_admin and invoice.location_id != effective_loc:
        return jsonify({'success': False, 'message': _('Access denied.')}), 403

    shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=invoice.location_id)) or \
                db.session.scalar(db.select(ShopSetting).filter_by(location_id=None))
    if not shop_info:
        shop_info = db.session.scalar(db.select(ShopSetting).limit(1))
    
    data = (request.get_json() if request.is_json else request.form) or {}
    points_to_use = safe_decimal(data.get('points', '0'))
    
    if points_to_use > invoice.customer.loyalty_points:
        return jsonify({'success': False, 'message': _('Insufficient points.')}), 400

    try:
        invoice.loyalty_points_used = points_to_use
        invoice.loyalty_discount_amount = points_to_use * (shop_info.loyalty_point_value if shop_info else 0)
        invoice.calculate_total()
        FinancialService.sync_invoice_status(invoice.id) # Ensure status is updated after loyalty redemption
        db.session.commit()
        return jsonify(FinancialService.get_invoice_summary_json(invoice))
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

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
    method = request.form.get('method') or 'Cash'
    reference = request.form.get('reference', '').strip()

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

@pos_bp.route('/print/<int:invoice_id>')
@login_required
@require_permission('process_sales')
def print_invoice(invoice_id):
    """Generates and serves the PDF receipt for a specific sale"""
    invoice = db.session.get(Invoice, invoice_id)
    if not invoice:
        flash(_('Invoice not found.'), 'danger')
        return redirect(url_for('pos.history'))

    is_admin = current_user.is_superuser or current_user.has_role('admin')
    effective_loc = current_user.location_id or db.session.scalar(db.select(Location.id).limit(1))
    if not is_admin and invoice.location_id != effective_loc:
        flash(_('Access denied.'), 'danger')
        return redirect(url_for('pos.history'))

    # This route provides the 'missing link' for direct sales in reports
    success, result = DocumentService.generate_invoice_pdf(invoice_id, doc_type='receipt')
    
    if success:
        return send_file(
            result,
            mimetype='application/pdf',
            as_attachment=False,
            download_name=f"receipt_{invoice_id}.pdf"
        )
    
    flash(result, 'danger')
    return redirect(url_for('pos.history'))