from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from sqlalchemy import desc, func, select
from sqlalchemy.orm import joinedload
from models import db, Customer, Ticket, Payment, Invoice, InvoiceItem
from decimal import Decimal
from .utils import require_permission
from services.core import ReportingService

report_bp = Blueprint('report', __name__)

@report_bp.route('/')
@login_required
@require_permission('view_reports')
def reports():
    selected_month = request.args.get('month')
    # Scoped financial reporting
    rev_stmt = select(func.sum(Payment.amount)).join(Ticket).where(Ticket.location_id == current_user.location_id)
    if selected_month:
        rev_stmt = rev_stmt.where(func.to_char(Payment.paid_at, 'YYYY-MM') == selected_month)
    gross_revenue = db.session.scalar(rev_stmt) or Decimal('0.00')
    
    cost_stmt = (
        select(func.sum(InvoiceItem.cost_price * InvoiceItem.quantity))
        .join(Invoice, InvoiceItem.invoice_id == Invoice.id)
        .join(Ticket, Invoice.ticket_id == Ticket.id)
        .where(Ticket.location_id == current_user.location_id)
    )
    if selected_month:
        cost_stmt = cost_stmt.where(func.to_char(Invoice.created_at, 'YYYY-MM') == selected_month)
    hardware_cost = db.session.scalar(cost_stmt) or Decimal('0.00')

    monthly_stats = {
        'total_tickets': db.session.scalar(
            select(func.count(Ticket.id)).where(Ticket.is_archived == False, Ticket.location_id == current_user.location_id)
        ),
        'gross_revenue': gross_revenue,
        'hardware_cost': hardware_cost,
        'net_profit': gross_revenue - hardware_cost,
        'selected_month': selected_month
    }

    # Standardized to SQLAlchemy 2.0 select syntax
    months_stmt = (
        select(func.to_char(Payment.paid_at, 'YYYY-MM'))
        .join(Ticket)
        .where(Ticket.location_id == current_user.location_id)
        .distinct()
    )
    months_p = db.session.execute(months_stmt).all()
    available_months = sorted(list(set([m[0] for m in months_p if m[0]])), reverse=True)

    tickets_stmt = select(Ticket).options(
        joinedload(Ticket.customer),
        joinedload(Ticket.device)
    ).where(Ticket.location_id == current_user.location_id).order_by(desc(Ticket.created_at)).limit(5)
    recent_tickets = db.session.scalars(tickets_stmt).all()

    return render_template('reports.html', monthly_stats=monthly_stats, recent_tickets=recent_tickets, available_months=available_months)

@report_bp.route('/finance')
@login_required
@require_permission('view_reports')
def finance_report():
    selected_month = request.args.get('month')
    monthly_analysis = ReportingService.get_financial_analysis()
    return render_template('finance_report.html', 
                           total_revenue=Decimal('0.00'),
                           total_hardware_cost=Decimal('0.00'),
                           net_profit=Decimal('0.00'),
                           monthly_analysis=monthly_analysis,
                           selected_month=selected_month,
                           available_months=[m['month'] for m in monthly_analysis])