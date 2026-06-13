from datetime import datetime
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import desc, func, select
from sqlalchemy.orm import joinedload
from models import db, Customer, Ticket, Payment, Invoice, InvoiceItem, Location
from decimal import Decimal
from flask_babel import _
from .utils import require_permission
from services.core import ReportingService

report_bp = Blueprint('report', __name__)

@report_bp.route('/')
@login_required
@require_permission('view_reports')
def reports():
    """Summary view for branch performance KPIs"""
    selected_month = request.args.get('month')

    # UX Integrity: Discover locations for the branch switcher (Superusers only)
    locations = db.session.scalars(select(Location).order_by(Location.name)).all() if current_user.is_superuser else []

    if current_user.is_superuser:
        effective_loc_id = request.args.get('location_id', type=int) or current_user.location_id
        location_filter = (Ticket.location_id == effective_loc_id) if effective_loc_id else True
    else:
        if current_user.location_id is None:
            flash(_('You are not assigned to a location. Please contact an administrator.'), 'error')
            return redirect(url_for('main.dashboard'))
        effective_loc_id = current_user.location_id
        location_filter = (Ticket.location_id == effective_loc_id)

    # Scoped financial reporting with filter synchronization
    rev_stmt = select(func.sum(Payment.amount)).join(Ticket).where(location_filter)
    
    if selected_month and selected_month != 'all':
        rev_stmt = rev_stmt.where(func.to_char(Payment.paid_at, 'YYYY-MM') == selected_month)
    gross_revenue = db.session.scalar(rev_stmt) or Decimal('0.00')
    
    cost_stmt = (
        select(func.sum(InvoiceItem.cost_price * InvoiceItem.quantity))
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .join(Ticket, Invoice.ticket_id == Ticket.id)
        .where(location_filter)
    )
    if selected_month and selected_month != 'all':
        cost_stmt = cost_stmt.where(func.to_char(Invoice.created_at, 'YYYY-MM') == selected_month)
    hardware_cost = db.session.scalar(cost_stmt) or Decimal('0.00')
    
    # Calculate completed tickets for the KPI card
    completed_stmt = select(func.count(Ticket.id)).where(
        Ticket.current_phase.in_(['Finished', 'Already Taken']),
        location_filter
    )
    if selected_month and selected_month != 'all':
        completed_stmt = completed_stmt.where(func.to_char(Ticket.created_at, 'YYYY-MM') == selected_month)

    total_stmt = select(func.count(Ticket.id)).where(location_filter)
    if selected_month and selected_month != 'all':
        total_stmt = total_stmt.where(func.to_char(Ticket.created_at, 'YYYY-MM') == selected_month)

    monthly_stats = {
        'total_tickets': db.session.scalar(total_stmt) or 0,
        'completed_tickets': db.session.scalar(completed_stmt) or 0,
        'gross_revenue': gross_revenue,
        'hardware_cost': hardware_cost,
        'net_profit': gross_revenue - hardware_cost,
        'selected_month': selected_month
    }

    # INTEGRITY: Discover months from both ticket creation and payment activity
    t_months = select(func.to_char(Ticket.created_at, 'YYYY-MM').label('m')).where(location_filter)
    p_months = select(func.to_char(Payment.paid_at, 'YYYY-MM').label('m')).join(Ticket).where(location_filter)
    months_stmt = t_months.union(p_months)
    
    months_p = db.session.execute(months_stmt).scalars().all()
    available_months = sorted([m for m in months_p if m], reverse=True)
    
    # INTEGRITY: Synchronize temporal fallback logic
    if not available_months:
        available_months = [datetime.now().strftime('%Y-%m')]

    tickets_stmt = select(Ticket).options(
        joinedload(Ticket.customer),
        joinedload(Ticket.device),
        joinedload(Ticket.assigned_to_user)
    ).where(location_filter).order_by(desc(Ticket.created_at)).limit(5)
    recent_tickets = db.session.scalars(tickets_stmt).all()

    return render_template('reports/reports.html', 
                           monthly_stats=monthly_stats, 
                           recent_tickets=recent_tickets, 
                           available_months=available_months, 
                           selected_month=selected_month,
                           locations=locations,
                           current_location_id=effective_loc_id)

@report_bp.route('/finance')
@login_required
@require_permission('view_reports')
def finance_report():
    selected_month = request.args.get('month')

    # UX Integrity: Discover locations for the branch switcher (Superusers only)
    locations = db.session.scalars(select(Location).order_by(Location.name)).all() if current_user.is_superuser else []

    if current_user.is_superuser:
        effective_loc_id = request.args.get('location_id', type=int) or current_user.location_id
        location_filter = (Ticket.location_id == effective_loc_id) if effective_loc_id else True
    else:
        if current_user.location_id is None:
            flash(_('You are not assigned to a location. Please contact an administrator.'), 'error')
            return redirect(url_for('main.dashboard'))
        effective_loc_id = current_user.location_id
        location_filter = (Ticket.location_id == effective_loc_id)

    # UX Integrity: For superusers in global view, fallback to primary location for 
    # the analysis chart context to avoid an empty/broken dashboard state.
    analysis_loc_id = effective_loc_id
    if not analysis_loc_id and locations:
        analysis_loc_id = locations[0].id
    monthly_analysis = ReportingService.get_financial_analysis(analysis_loc_id) if analysis_loc_id else []
    
    # Sync aggregate KPIs with current filters
    rev_stmt = select(func.sum(Payment.amount)).join(Ticket).where(location_filter)
    cost_stmt = (
        select(func.sum(InvoiceItem.cost_price * InvoiceItem.quantity))
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .join(Ticket, Invoice.ticket_id == Ticket.id)
        .where(location_filter)
    )
    
    if selected_month and selected_month != 'all':
        rev_stmt = rev_stmt.where(func.to_char(Payment.paid_at, 'YYYY-MM') == selected_month)
        cost_stmt = cost_stmt.where(func.to_char(Invoice.created_at, 'YYYY-MM') == selected_month)

    total_revenue = db.session.scalar(rev_stmt) or Decimal('0.00')
    total_hardware_cost = db.session.scalar(cost_stmt) or Decimal('0.00')
    
    # INTEGRITY: Discover months from both ticket creation and payment activity to ensure full data reachability
    t_months_stmt = select(func.to_char(Ticket.created_at, 'YYYY-MM').label('m')).where(location_filter)
    p_months_stmt = select(func.to_char(Payment.paid_at, 'YYYY-MM').label('m')).join(Ticket).where(location_filter)
    
    all_months_query = t_months_stmt.union(p_months_stmt)
    available_months = sorted([m for m in db.session.execute(all_months_query).scalars().all() if m], reverse=True)
    
    # INTEGRITY: Ensure a valid temporal context exists for the filter UI
    if not available_months:
        available_months = [m['month'] for m in monthly_analysis] if monthly_analysis else [datetime.now().strftime('%Y-%m')]

    # Fetch detailed payment history for the table
    payment_stmt = select(Payment).options(
        joinedload(Payment.ticket).joinedload(Ticket.customer),
        joinedload(Payment.ticket).joinedload(Ticket.device)
    ).join(Ticket).where(location_filter)
    
    if selected_month and selected_month != 'all':
        payment_stmt = payment_stmt.where(func.to_char(Payment.paid_at, 'YYYY-MM') == selected_month)
    payment_history = db.session.scalars(payment_stmt.order_by(desc(Payment.paid_at))).all()

    # Fetch material usage (Invoice Items) for hardware tracking
    material_stmt = select(InvoiceItem).options(
        joinedload(InvoiceItem.invoice).joinedload(Invoice.ticket).joinedload(Ticket.customer),
        joinedload(InvoiceItem.invoice).joinedload(Invoice.ticket).joinedload(Ticket.device)
    ).join(Invoice).join(Ticket).where(location_filter)
    
    if selected_month and selected_month != 'all':
        material_stmt = material_stmt.where(func.to_char(Invoice.created_at, 'YYYY-MM') == selected_month)
    material_usage = db.session.scalars(material_stmt.order_by(desc(Invoice.created_at))).all()

    return render_template('reports/finance_report.html', 
                           total_revenue=total_revenue,
                           total_hardware_cost=total_hardware_cost,
                           net_profit=total_revenue - total_hardware_cost,
                           monthly_analysis=monthly_analysis,
                           selected_month=selected_month,
                           available_months=available_months,
                           payment_history=payment_history,
                           material_usage=material_usage,
                           locations=locations,
                           current_location_id=effective_loc_id)