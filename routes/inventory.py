from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload

from models import InvoiceItem, Location, SparePart, SparePartPriceHistory, db
from .utils import require_permission, safe_decimal

inventory_bp = Blueprint('inventory', __name__)

@inventory_bp.route('/')
@login_required
@require_permission('view_inventory')
def manage_inventory():
    """Dedicated inventory management for spare parts and stock levels"""
    page = request.args.get('page', 1, type=int)
    query = request.args.get('q', '').strip()
    selected_location = request.args.get('location_id', type=int)
    
    is_admin = current_user.is_superuser or current_user.has_role('admin') # Define once

    locations = []
    if current_user.is_superuser:
        # INTEGRITY: Only superusers can bypass branch scoping for cross-location management
        locations = db.session.scalars(db.select(Location).order_by(Location.name)).all()
        location_filter = (SparePart.location_id == selected_location) if selected_location else True
    else:
        location_filter = (SparePart.location_id == current_user.location_id)

    stmt = db.select(SparePart).where(location_filter)
    
    if query:
        # Search by name (case-insensitive) or SKU/Barcode
        stmt = stmt.where(or_(
            SparePart.name.ilike(f'%{query}%'),
            SparePart.sku.ilike(f'%{query}%')
        ))
        
    stmt = stmt.order_by(SparePart.name)
    parts = db.paginate(stmt, page=page, per_page=15)
    return render_template('parts/manage_parts.html', 
                           parts=parts, 
                           search_query=query, 
                           locations=locations, 
                           selected_location=selected_location)

@inventory_bp.route('/add', methods=['POST'])
@login_required
@require_permission('manage_inventory')
def add_part():
    """Endpoint for creating a new catalog part"""
    query = request.args.get('q', '').strip()
    selected_location = request.args.get('location_id', type=int)
    is_admin = current_user.is_superuser or current_user.has_role('admin')

    locations = []
    if current_user.is_superuser:
        locations = db.session.scalars(db.select(Location).order_by(Location.name)).all()
        location_filter = (SparePart.location_id == selected_location) if selected_location else True
    else:
        location_filter = (SparePart.location_id == current_user.location_id)

    sku = request.form.get('sku', '').strip().upper() or None
    name = request.form.get('name', '').strip()
    stock = request.form.get('stock_quantity', 0, type=int)
    cost = safe_decimal(request.form.get('cost', '0.00'))
    selling_price = safe_decimal(request.form.get('selling_price', '0.00'))
    
    if not name:
        flash(_('Part name is required.'), 'danger')
        return render_template('parts/manage_parts.html', parts=db.paginate(db.select(SparePart).where(location_filter).order_by(SparePart.name), page=1, per_page=15),
                               search_query=query, locations=locations, selected_location=selected_location,
                               sku=sku, name=name, stock_quantity=stock, cost=cost, selling_price=selling_price)

    # INTEGRITY: Respect the active branch context for superusers
    loc_id = (selected_location if is_admin and selected_location else current_user.location_id) or \
             db.session.scalar(db.select(Location.id).limit(1))
    
    # Fetch parts for the template on error
    parts_for_template = db.paginate(db.select(SparePart).where(location_filter).order_by(SparePart.name), page=1, per_page=15)


    # Integrity: Check for duplicate names at this location
    exists = db.session.scalar(db.select(SparePart).where(
        func.lower(SparePart.name) == func.lower(name),
        SparePart.location_id == loc_id
    ))
    if exists:
        flash(_('A part with this name already exists in your inventory.'), 'danger')
        return render_template('parts/manage_parts.html', parts=parts_for_template,
                               search_query=query, locations=locations, selected_location=selected_location,
                               sku=sku, name=name, stock_quantity=stock, cost=cost, selling_price=selling_price)

    # Integrity: Ensure SKU uniqueness per location to prevent POS/Search collisions
    if sku:
        sku_exists = db.session.scalar(db.select(SparePart).where(
            SparePart.sku == sku, SparePart.location_id == loc_id
        ))
        if sku_exists:
            flash(_('A part with this SKU already exists in your inventory.'), 'danger')
            return render_template('parts/manage_parts.html', parts=parts_for_template,
                                   search_query=query, locations=locations, selected_location=selected_location,
                                   sku=sku, name=name, stock_quantity=stock, cost=cost, selling_price=selling_price)

    if stock < 0 or cost < 0 or selling_price < 0:
        flash(_('Stock, cost, and price cannot be negative.'), 'danger')
        return render_template('parts/manage_parts.html', parts=parts_for_template,
                               search_query=query, locations=locations, selected_location=selected_location,
                               sku=sku, name=name, stock_quantity=stock, cost=cost, selling_price=selling_price)

    new_part = SparePart(
        sku=sku,
        name=name,
        cost=cost,
        selling_price=selling_price,
        stock_quantity=stock,
        location_id=loc_id
    )
    db.session.add(new_part)
        
    # INTEGRITY: Create initial price history record to start the movement tracking
    history = SparePartPriceHistory(
        spare_part=new_part,
        old_cost=None,
        new_cost=cost,
        old_price=None,
        new_price=selling_price,
        user_id=current_user.id
    )
    db.session.add(history)
    try:
        db.session.commit()
        flash(_('New part added to inventory.'), 'success')
        return redirect(url_for('inventory.manage_inventory', location_id=selected_location))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Part addition error: {str(e)}")
        flash(_('Error adding part to inventory.'), 'danger')
        # UX Integrity: Return form data on error to prevent data loss
        return render_template('parts/manage_parts.html', parts=parts_for_template,
                               search_query=query, locations=locations, selected_location=selected_location,
                               sku=sku, name=name, stock_quantity=stock, cost=cost, selling_price=selling_price)

@inventory_bp.route('/edit/<int:part_id>', methods=['POST'])
@login_required
@require_permission('manage_inventory')
def edit_part(part_id):
    """Endpoint for updating existing part specifications"""
    query = request.args.get('q', '').strip()
    selected_location = request.args.get('location_id', type=int)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    
    locations = []
    if current_user.is_superuser:
        locations = db.session.scalars(db.select(Location).order_by(Location.name)).all()
        location_filter = (SparePart.location_id == selected_location) if selected_location else True
    else:
        location_filter = (SparePart.location_id == current_user.location_id)

    # Fetch parts for the template on error
    parts_for_template = db.paginate(db.select(SparePart).where(location_filter).order_by(SparePart.name), page=1, per_page=15)

    part = db.session.get(SparePart, part_id)
    if not part or (not is_admin and part.location_id != current_user.location_id):
        flash(_('Part not found.'), 'danger')
        return render_template('parts/manage_parts.html', parts=parts_for_template, search_query=query, locations=locations, selected_location=selected_location)

    # Store current values to check for movement
    old_cost = part.cost
    old_price = part.selling_price

    sku = request.form.get('sku', '').strip().upper() or None
    name = request.form.get('name', '').strip()
    stock = request.form.get('stock_quantity', 0, type=int)
    cost = safe_decimal(request.form.get('cost', '0.00'))
    selling_price = safe_decimal(request.form.get('selling_price', '0.00'))

    if not name:
        flash(_('Part name is required.'), 'danger')
        return render_template('parts/manage_parts.html', parts=parts_for_template,
                               search_query=query, locations=locations, selected_location=selected_location,
                               part=part, sku=sku, name=name, stock_quantity=stock, cost=cost, selling_price=selling_price, is_active='is_active' in request.form)

    # Integrity: Check for duplicate names (excluding current part) at this location
    exists = db.session.scalar(db.select(SparePart).where(
        func.lower(SparePart.name) == func.lower(name),
        SparePart.location_id == part.location_id,
        SparePart.id != part_id
    ))
    if exists:
        flash(_('Another part already uses this name.'), 'danger')
        return render_template('parts/manage_parts.html', parts=parts_for_template,
                               search_query=query, locations=locations, selected_location=selected_location,
                               part=part, sku=sku, name=name, stock_quantity=stock, cost=cost, selling_price=selling_price, is_active='is_active' in request.form)

    # Integrity: Check for SKU collisions excluding the current record
    if sku:
        sku_exists = db.session.scalar(db.select(SparePart).where(
            SparePart.sku == sku, SparePart.location_id == part.location_id, SparePart.id != part_id
        ))
        if sku_exists:
            flash(_('Another part already uses this SKU.'), 'danger')
            return render_template('parts/manage_parts.html', parts=parts_for_template,
                                   search_query=query, locations=locations, selected_location=selected_location,
                                   part=part, sku=sku, name=name, stock_quantity=stock, cost=cost, selling_price=selling_price, is_active='is_active' in request.form)

    if stock < 0 or cost < 0 or selling_price < 0:
        flash(_('Stock, cost, and price cannot be negative.'), 'danger')
        return render_template('parts/manage_parts.html', parts=parts_for_template,
                               search_query=query, locations=locations, selected_location=selected_location,
                               part=part, sku=sku, name=name, stock_quantity=stock, cost=cost, selling_price=selling_price, is_active='is_active' in request.form)

    part.sku = sku
    part.name = name
    part.cost = cost
    part.selling_price = selling_price
    part.stock_quantity = stock
    part.is_active = 'is_active' in request.form
    
    # INTEGRITY: Record movement if price or cost changed
    if old_cost != cost or old_price != selling_price:
        history = SparePartPriceHistory(
            spare_part=part,
            old_cost=old_cost,
            new_cost=cost,
            old_price=old_price,
            new_price=selling_price,
            user_id=current_user.id
        )
        db.session.add(history)

    try:
        db.session.commit()
        flash(_('Inventory item updated.'), 'success')
        return redirect(url_for('inventory.manage_inventory', location_id=selected_location))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Part update error: {str(e)}")
        flash(_('Error updating inventory item.'), 'danger')
        # UX Integrity: Return form data on error to prevent data loss
        return render_template('parts/manage_parts.html', parts=parts_for_template,
                               search_query=query, locations=locations, selected_location=selected_location,
                               part=part, sku=sku, name=name, stock_quantity=stock, cost=cost, selling_price=selling_price, is_active='is_active' in request.form)

@inventory_bp.route('/history/<int:part_id>')
@login_required
@require_permission('manage_inventory')
def get_part_history(part_id):
    """Endpoint for retrieval of price movement history for inventory visualization"""
    part = db.session.get(SparePart, part_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if not part or (not is_admin and part.location_id != current_user.location_id):
        return jsonify({'error': _('Part not found')}), 404

    history = db.session.scalars(
        db.select(SparePartPriceHistory)
        .where(SparePartPriceHistory.spare_part_id == part_id)
        .order_by(SparePartPriceHistory.changed_at.asc())
    ).all()

    return jsonify({
        'name': part.name,
        'labels': [h.changed_at.strftime('%Y-%m-%d') for h in history],
        'cost_data': [float(h.new_cost) for h in history],
        'price_data': [float(h.new_price) for h in history]
    })

@inventory_bp.route('/delete/<int:part_id>', methods=['POST'])
@login_required
@require_permission('manage_inventory')
def delete_part(part_id):
    """Endpoint for permanent removal of inventory items"""
    selected_location = request.args.get('location_id', type=int)

    part = db.session.get(SparePart, part_id)
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    if part and (is_admin or part.location_id == current_user.location_id):
        # INTEGRITY: Check for linked InvoiceItem records before deletion
        linked_invoice_items = db.session.scalar(db.select(func.count(InvoiceItem.id)).where(InvoiceItem.spare_part_id == part_id))
        if linked_invoice_items > 0:
            flash(_('Cannot delete part: It is linked to existing sales records. Archive it instead or remove from sales first.'), 'danger')
            return redirect(url_for('inventory.manage_inventory', location_id=selected_location))

        try:
            db.session.delete(part)
            db.session.commit()
            flash(_('Part deleted.'), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Part deletion error: {str(e)}")
            flash(_('Error deleting part. It may be linked to existing tickets.'), 'danger')
    else:
        flash(_('Part not found or access denied.'), 'danger')
    return redirect(url_for('inventory.manage_inventory', location_id=selected_location))