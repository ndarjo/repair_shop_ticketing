from datetime import datetime
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import _
from flask_login import login_required, current_user
from sqlalchemy import desc, func
from sqlalchemy.orm import joinedload, selectinload

from models import Customer, Invoice, InvoiceItem, Location, Payment, Ticket, ShopSetting, db
from services.core import ReportingService
from .utils import require_permission

report_bp = Blueprint('report', __name__)

@report_bp.route('/')
@login_required
@require_permission('view_reports')
def reports():
    """Summary view for branch performance KPIs"""
    selected_month = request.args.get('month')
    selected_location = request.args.get('location_id', type=int)

    # UI CONSISTENCY: Align branch switching permissions with the inventory and finance modules
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    locations = db.session.scalars(db.select(Location).order_by(Location.name)).all() if is_admin else []

    if is_admin:
        effective_loc_id = selected_location
        location_filter = (Invoice.location_id == selected_location) if selected_location else True
    else:
        if current_user.location_id is None:
            flash(_('You are not assigned to a location. Please contact an administrator.'), 'danger')
            return redirect(url_for('main.dashboard'))
        effective_loc_id = current_user.location_id
        location_filter = (Invoice.location_id == effective_loc_id)

    # Fetch settings scoped to the effective location
    shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=effective_loc_id)) or \
                db.session.scalar(db.select(ShopSetting).filter_by(location_id=None)) or \
                db.session.scalar(db.select(ShopSetting).limit(1))

    # INTEGRITY: Fetch objects with eager loading to access computed properties safely.
    rev_stmt = db.select(
        Payment,
        Invoice
    ).join(Invoice, Payment.invoice_id == Invoice.id)\
     .options(joinedload(Invoice.ticket).selectinload(Ticket.ticket_services), selectinload(Invoice.items))\
     .where(location_filter)
    
    if selected_month and selected_month != 'all':
        rev_stmt = rev_stmt.where(func.to_char(Payment.paid_at, 'YYYY-MM') == selected_month)
    
    cost_stmt = (
        db.select(func.sum(InvoiceItem.cost_price * InvoiceItem.quantity))
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .where(location_filter)
    )
    if selected_month and selected_month != 'all':
        cost_stmt = cost_stmt.where(func.to_char(Invoice.created_at, 'YYYY-MM') == selected_month)
    hardware_cost = db.session.scalar(cost_stmt) or Decimal('0.00')
    
    # Calculate completed tickets for the KPI card
    ticket_loc_filter = (Ticket.location_id == effective_loc_id) if effective_loc_id else True
    completed_stmt = db.select(func.count(Ticket.id)).where(
        Ticket.current_phase.in_(['Finished', 'Already Taken']),
        ticket_loc_filter
    )
    if selected_month and selected_month != 'all':
        completed_stmt = completed_stmt.where(func.to_char(Ticket.created_at, 'YYYY-MM') == selected_month)

    total_stmt = db.select(func.count(Ticket.id)).where(ticket_loc_filter)
    if selected_month and selected_month != 'all':
        total_stmt = total_stmt.where(func.to_char(Ticket.created_at, 'YYYY-MM') == selected_month)

    # Calculate accurate net profit by iterating through transactions to respect historical tax ratios
    rev_results = db.session.execute(rev_stmt).all()
    net_revenue_total = Decimal('0.00')
    gross_revenue_total = Decimal('0.00')
    
    for payment, invoice in rev_results:
        gross_revenue_total += payment.amount
        if invoice.total_amount and invoice.total_amount > 0:
            tax_ratio = invoice.tax_amount / invoice.total_amount
            net_revenue_total += payment.amount * (1 - tax_ratio)
        else:
            net_revenue_total += payment.amount

    monthly_stats = {
        'total_tickets': db.session.scalar(total_stmt) or 0,
        'completed_tickets': db.session.scalar(completed_stmt) or 0,
        'gross_revenue': gross_revenue_total,
        'hardware_cost': hardware_cost,
        'net_profit': net_revenue_total - hardware_cost,
        'selected_month': selected_month
    }

    # INTEGRITY: Discover months from both ticket creation and payment activity
    t_months = db.select(func.to_char(Ticket.created_at, 'YYYY-MM').label('m')).where(ticket_loc_filter)
    p_months = db.select(func.to_char(Payment.paid_at, 'YYYY-MM').label('m')).join(Invoice, Payment.invoice_id == Invoice.id).where(location_filter)
    months_stmt = t_months.union(p_months)
    
    months_p = db.session.scalars(months_stmt).all()
    available_months = sorted([m for m in months_p if m], reverse=True)
    
    # UI Consistency: Ensure the dropdown has at least a current context fallback
    if not available_months:
        # Try to pull months from financial analysis service for parity with finance_report
        analysis = ReportingService.get_financial_analysis(effective_loc_id)
        available_months = [m['month'] for m in analysis] if analysis else [datetime.now().strftime('%Y-%m')]

    # UX: Fetch recent invoices (both Repair and POS) for the activity feed
    invoice_stmt = db.select(Invoice).options(joinedload(Invoice.customer), joinedload(Invoice.ticket).joinedload(Ticket.customer)).where(location_filter).order_by(desc(Invoice.created_at)).limit(5)
    recent_activity = db.session.scalars(invoice_stmt).all()

    return render_template('reports/reports.html', 
                           monthly_stats=monthly_stats, 
                           recent_tickets=recent_activity, 
                           available_months=available_months, 
                           selected_month=selected_month,
                           locations=locations,
                           selected_location=effective_loc_id,
                           shop_info=shop_info)

@report_bp.route('/finance')
@login_required
@require_permission('view_reports')
def finance_report():
    start_month = request.args.get('start_month')
    end_month = request.args.get('end_month')
    month = request.args.get('month')

    # Handle backward compatibility and quick navigation buttons
    if month and month != 'all' and not start_month and not end_month:
        start_month = end_month = month
    
    selected_month = start_month if start_month == end_month else None
    selected_location = request.args.get('location_id', type=int)

    # UI Consistency: Enable location switching for all administrative staff
    is_admin = current_user.is_superuser or current_user.has_role('admin')
    locations = db.session.scalars(db.select(Location).order_by(Location.name)).all() if is_admin else []

    if is_admin:
        effective_loc_id = selected_location
        location_filter = (Invoice.location_id == selected_location) if selected_location else True
    else:
        if current_user.location_id is None:
            flash(_('You are not assigned to a location. Please contact an administrator.'), 'danger')
            return redirect(url_for('main.dashboard'))
        effective_loc_id = current_user.location_id
        location_filter = (Invoice.location_id == effective_loc_id)

    # INTEGRITY: Fetch settings scoped to the effective location
    shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=effective_loc_id)) or \
                db.session.scalar(db.select(ShopSetting).filter_by(location_id=None)) or \
                db.session.scalar(db.select(ShopSetting).limit(1))

    # Integrity: Retrieve financial trends scoped to the selected location or all locations.
    monthly_analysis = ReportingService.get_financial_analysis(effective_loc_id)
    
    # Filter monthly analysis trend chart if range is provided
    if start_month or end_month:
        monthly_analysis = [
            m for m in monthly_analysis 
            if (not start_month or m['month'] >= start_month) and 
               (not end_month or m['month'] <= end_month)
        ]

    # INTEGRITY: Align with Dashboard aggregate logic for financial accuracy.
    rev_stmt = db.select(
        Payment,
        Invoice
    ).join(Invoice, Payment.invoice_id == Invoice.id)\
     .options(joinedload(Invoice.ticket).selectinload(Ticket.ticket_services), selectinload(Invoice.items))\
     .where(location_filter)

    cost_stmt = (
        db.select(func.sum(InvoiceItem.cost_price * InvoiceItem.quantity))
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .where(location_filter)
    )
    
    if start_month:
        rev_stmt = rev_stmt.where(func.to_char(Payment.paid_at, 'YYYY-MM') >= start_month)
        cost_stmt = cost_stmt.where(func.to_char(Invoice.created_at, 'YYYY-MM') >= start_month)
    if end_month:
        rev_stmt = rev_stmt.where(func.to_char(Payment.paid_at, 'YYYY-MM') <= end_month)
        cost_stmt = cost_stmt.where(func.to_char(Invoice.created_at, 'YYYY-MM') <= end_month)

    # Aggregate revenue while respecting historical tax ratios per invoice
    rev_results = db.session.execute(rev_stmt).all()
    net_revenue_total = Decimal('0.00')
    total_revenue = Decimal('0.00')
    
    for payment, invoice in rev_results:
        total_revenue += payment.amount
        if invoice.total_amount and invoice.total_amount > 0:
            tax_ratio = invoice.tax_amount / invoice.total_amount
            net_revenue_total += payment.amount * (1 - tax_ratio)
        else:
            net_revenue_total += payment.amount

    total_hardware_cost = db.session.scalar(cost_stmt) or Decimal('0.00')

    # INTEGRITY: Discover months from both ticket creation and payment activity to ensure full data reachability
    ticket_loc_filter = (Ticket.location_id == effective_loc_id) if effective_loc_id else True
    t_months_stmt = db.select(func.to_char(Ticket.created_at, 'YYYY-MM').label('m')).where(ticket_loc_filter)
    p_months_stmt = db.select(func.to_char(Payment.paid_at, 'YYYY-MM').label('m')).join(Invoice, Payment.invoice_id == Invoice.id).where(location_filter)
    
    all_months_query = t_months_stmt.union(p_months_stmt)
    available_months = sorted([m for m in db.session.scalars(all_months_query).all() if m], reverse=True)
    
    # INTEGRITY: Ensure a valid temporal context exists for the filter UI
    if not available_months:
        available_months = [m['month'] for m in monthly_analysis] if monthly_analysis else [datetime.now().strftime('%Y-%m')]

    # Fetch detailed payment history for the table
    payment_stmt = db.select(Payment).options(
        joinedload(Payment.ticket).joinedload(Ticket.customer),
        joinedload(Payment.ticket).joinedload(Ticket.device),
        joinedload(Payment.invoice).joinedload(Invoice.customer)
    ).join(Invoice, Payment.invoice_id == Invoice.id).where(location_filter)
    
    if start_month:
        payment_stmt = payment_stmt.where(func.to_char(Payment.paid_at, 'YYYY-MM') >= start_month)
    if end_month:
        payment_stmt = payment_stmt.where(func.to_char(Payment.paid_at, 'YYYY-MM') <= end_month)

    payment_history = db.session.scalars(payment_stmt.order_by(desc(Payment.paid_at))).all()

    # Fetch material usage (Invoice Items) for hardware tracking
    material_stmt = db.select(InvoiceItem).options(
        joinedload(InvoiceItem.invoice).joinedload(Invoice.customer),
        joinedload(InvoiceItem.invoice).joinedload(Invoice.ticket).joinedload(Ticket.customer),
        joinedload(InvoiceItem.invoice).joinedload(Invoice.ticket).joinedload(Ticket.device)
    ).join(Invoice).where(location_filter)
    
    if start_month:
        material_stmt = material_stmt.where(func.to_char(Invoice.created_at, 'YYYY-MM') >= start_month)
    if end_month:
        material_stmt = material_stmt.where(func.to_char(Invoice.created_at, 'YYYY-MM') <= end_month)

    material_usage = db.session.scalars(material_stmt.order_by(desc(Invoice.created_at))).all()

    return render_template('reports/finance_report.html', 
                           total_revenue=total_revenue,
                           total_hardware_cost=total_hardware_cost,
                           net_profit=net_revenue_total - total_hardware_cost,
                           monthly_analysis=monthly_analysis,
                           selected_month=selected_month,
                           start_month=start_month,
                           end_month=end_month,
                           available_months=available_months,
                           payment_history=payment_history,
                           material_usage=material_usage,
                           locations=locations,
                           selected_location=effective_loc_id,
                           shop_info=shop_info)