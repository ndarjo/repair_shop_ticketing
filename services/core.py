import os
from datetime import datetime
from decimal import Decimal
import uuid
from typing import Tuple, Any, Optional, Dict, List
from flask import current_app
from flask_babel import _
from sqlalchemy import func, or_, desc
from sqlalchemy.orm import joinedload, selectinload
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import io
from models import db, Ticket, Payment, Note, Invoice, Service, SparePart, InvoiceItem, TicketService as TicketServiceBridge, Customer, Device, ShopSetting, User

class FinancialService:
    @staticmethod
    def get_or_create_invoice(ticket_id: int) -> Invoice:
        """Ensures a draft or active invoice exists for the ticket"""
        invoice = db.session.scalar(db.select(Invoice).filter_by(ticket_id=ticket_id))
        if not invoice:
            invoice = Invoice(
                invoice_number=f"INV-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
                ticket_id=ticket_id,
                status='Draft'
            )
            db.session.add(invoice)
            db.session.flush()
        return invoice

    @staticmethod
    def sync_invoice_status(invoice_id: int):
        """Re-evaluates invoice status (Paid/Partial/Unpaid) based on current payments"""
        invoice = db.session.get(Invoice, invoice_id)
        if not invoice:
            return
        
        # INTEGRITY: If invoice is empty and no money taken, keep it in Draft
        if invoice.total_amount == 0 and invoice.full_payment_received == 0:
            invoice.status = 'Draft'
            db.session.flush()
            return
            
        balance = invoice.remaining_balance
        if balance <= 0:
            invoice.status = 'Paid'
        elif balance < invoice.total_amount:
            invoice.status = 'Partial'
        else:
            invoice.status = 'Unpaid'
        db.session.flush()

    @staticmethod
    def sync_ticket_summaries(ticket_id: int):
        """Synchronizes ticket actual_cost (wholesale) with current invoice items"""
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            return

        # Aggregate wholesale costs from all parts on all invoices for this ticket
        wholesale_sum = db.session.scalar(
            db.select(func.sum(InvoiceItem.cost_price * InvoiceItem.quantity))
            .join(Invoice)
            .filter(Invoice.ticket_id == ticket_id)
        ) or Decimal('0.00')

        ticket.actual_cost = wholesale_sum
        db.session.flush()

    @staticmethod
    def void_payment(payment_id: int, user_id: int) -> Tuple[bool, str]:
        """Voids a payment record and re-evaluates the associated invoice status"""
        payment = db.session.get(Payment, payment_id)
        if not payment:
            return False, _('Payment not found')

        invoice_id = payment.invoice_id
        db.session.delete(payment)
        db.session.flush()

        if invoice_id:
            FinancialService.sync_invoice_status(invoice_id)
        return True, _('Payment voided successfully')

    @staticmethod
    def record_payment(ticket_id: int, amount: Decimal, method: str, reference: str, user_id: int) -> Tuple[bool, Any]:
        """Records a payment, updates invoice status, and creates an automated note"""
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            return False, _('Ticket not found')

        invoice = FinancialService.get_or_create_invoice(ticket_id)

        payment = Payment(
            ticket_id=ticket.id,
            invoice_id=invoice.id,
            user_id=user_id,
            amount=amount,
            payment_method=method,
            transaction_reference=reference,
            paid_at=datetime.now()
        )
        db.session.add(payment)
        db.session.flush()

        user = db.session.get(User, user_id)
        currency_map = {'USD': '$', 'IDR': 'Rp', 'EUR': '€', 'GBP': '£'}
        symbol = currency_map.get(user.currency, '$') if user else '$'
        decimals = user.currency_decimals if user and user.currency_decimals is not None else 2

        FinancialService.sync_invoice_status(invoice.id)

        note_type = _('Payment Received') if amount > 0 else _('Change Given / Refund')
        note_content = _('%(type)s: %(symbol)s%(amount)s. Method: %(method)s. Ref: %(ref)s', 
                         type=note_type, symbol=symbol, amount=f"{abs(amount):.{decimals}f}", method=method, ref=reference)

        note = Note(
            ticket_id=ticket.id,
            user_id=user_id,
            note_type=note_type,
            content=note_content,
            is_internal=True
        )
        db.session.add(note)
        return True, payment

    @staticmethod
    def get_ticket_profitability(ticket_id: int) -> Dict[str, Any]:
        """Calculates revenue, wholesale cost, and net profit for a specific ticket"""
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            return {}

        revenue = ticket.grand_total
        cost = ticket.actual_cost  # Synced wholesale cost
        profit = revenue - cost

        return {
            'revenue': revenue,
            'cost': cost,
            'profit': profit,
            'margin_percentage': (profit / revenue * 100) if revenue > 0 else 0
        }

class InventoryService:
    @staticmethod
    def add_service_to_ticket(ticket_id: int, service_id: int, quantity: int) -> Tuple[bool, Any]:
        """Attaches a catalog service to a ticket and updates the invoice"""
        service = db.session.get(Service, service_id)
        if not service:
            return False, _('Service not found')
        
        invoice = FinancialService.get_or_create_invoice(ticket_id)
        
        ts = TicketServiceBridge(
            ticket_id=ticket_id,
            service_id=service_id,
            quantity=quantity,
            price_charged=service.price
        )
        db.session.add(ts)
        db.session.flush()
        invoice.calculate_total()
        FinancialService.sync_ticket_summaries(ticket_id)
        FinancialService.sync_invoice_status(invoice.id)
        return True, ts

    @staticmethod
    def add_part_to_ticket(ticket_id: int, part_id: Optional[int], manual_name: Optional[str], 
                           quantity: int, price: Optional[Decimal], cost: Optional[Decimal]) -> Tuple[bool, Any]:
        """Adds an inventory or manual part to a ticket and updates the invoice"""
        description = ""
        item_price = Decimal('0.00')
        item_cost = Decimal('0.00')
        spare_part_id = None

        if part_id:
            # Concurrency check: Lock the row for update to ensure stock integrity
            part = db.session.execute(db.select(SparePart).filter_by(id=part_id).with_for_update()).scalar()
            if part:
                description = part.name
                item_price = price if price is not None else part.selling_price
                item_cost = part.cost
                spare_part_id = part.id
                
                # Inventory Management: Decrement stock
                if part.stock_quantity < quantity:
                    return False, _('Insufficient stock for "%(name)s". Current: %(qty)s', name=part.name, qty=part.stock_quantity)
                part.stock_quantity -= quantity

        elif manual_name:
            description = manual_name
            item_price = price if price is not None else Decimal('0.00')
            item_cost = cost if cost else Decimal('0.00')
        
        if not description:
            return False, _('Invalid part details')

        invoice = FinancialService.get_or_create_invoice(ticket_id)
        
        item = InvoiceItem(
            invoice_id=invoice.id,
            spare_part_id=spare_part_id,
            description=description,
            quantity=quantity,
            cost_price=item_cost,
            unit_price=item_price,
            total_price=item_price * quantity
        )
        db.session.add(item)
        db.session.flush()
        invoice.calculate_total()
        FinancialService.sync_ticket_summaries(ticket_id)
        FinancialService.sync_invoice_status(invoice.id)
        return True, item

    @staticmethod
    def remove_service(ticket_id: int, ts_id: int) -> Tuple[bool, Optional[str]]:
        """Removes a service and updates the invoice total"""
        ts = db.session.get(TicketServiceBridge, ts_id)
        if not ts or ts.ticket_id != ticket_id:
            return False, _('Service entry not found')
            
        invoice = db.session.scalar(db.select(Invoice).filter_by(ticket_id=ticket_id))
        db.session.delete(ts)
        db.session.flush()
        
        if invoice:
            invoice.calculate_total()
            FinancialService.sync_invoice_status(invoice.id)
        FinancialService.sync_ticket_summaries(ticket_id)
        return True, None

    @staticmethod
    def remove_part(item_id: int) -> Tuple[bool, Optional[str]]:
        """Removes a part, restores inventory stock, and updates invoice"""
        item = db.session.get(InvoiceItem, item_id)
        if not item:
            return False, _('Part entry not found')

        # Inventory Management: Restore stock if linked to a catalog part
        if item.spare_part_id:
            # Integrity: Lock the part row for update to prevent race conditions during stock restoration
            part = db.session.execute(db.select(SparePart).filter_by(id=item.spare_part_id).with_for_update()).scalar()
            if part:
                part.stock_quantity += item.quantity

        invoice = item.invoice
        ticket_id = invoice.ticket_id
        db.session.delete(item)
        db.session.flush()
        invoice.calculate_total()
        FinancialService.sync_invoice_status(invoice.id)
        FinancialService.sync_ticket_summaries(ticket_id)
        return True, None

class CustomerService:
    @staticmethod
    def create_customer(name: str, phone: str, address: str = '', location_id: Optional[int] = None) -> Tuple[bool, Any]:
        """Standardized customer creation logic used by both forms and AJAX"""
        if not name or not phone:
            return False, _('Name and phone are required')
        try:
            customer = Customer(name=name, phone=phone, address=address, location_id=location_id)
            db.session.add(customer)
            db.session.flush()
            return True, customer
        except Exception as e:
            current_app.logger.error(f"Customer creation failed: {str(e)}")
            return False, _('Failed to create customer record')

class DeviceService:
    @staticmethod
    def create_device(customer_id: int, device_type: str, brand: str, **kwargs) -> Tuple[bool, Any]:
        """Standardized device creation logic"""
        if not all([customer_id, device_type, brand]):
            return False, _('Customer, Type, and Brand are required')
        try:
            device = Device(
                customer_id=customer_id,
                device_type=device_type,
                brand=brand,
                model_number=kwargs.get('model_number'),
                serial_number=kwargs.get('serial_number'),
                color=kwargs.get('color'),
                cpu=kwargs.get('cpu'),
                ram=kwargs.get('ram'),
                storage_type=kwargs.get('storage_type'),
                storage_capacity=kwargs.get('storage_capacity'),
                notes=kwargs.get('notes')
            )
            db.session.add(device)
            db.session.flush()
            return True, device
        except Exception as e:
            current_app.logger.error(f"Device creation failed: {str(e)}")
            return False, _('Failed to create device record')

class ReportingService:
    @staticmethod
    def get_financial_analysis(location_id: int) -> List[Dict[str, Any]]:
        """Aggregates revenue and costs by month for financial reporting"""
        month_expr = func.to_char(Payment.paid_at, 'YYYY-MM')
        rev_stmt = db.select(
            month_expr.label('month'),
            func.sum(Payment.amount)
        ).join(Ticket, Payment.ticket_id == Ticket.id)\
         .filter(Ticket.location_id == location_id)\
         .group_by(month_expr)
        rev_results = db.session.execute(rev_stmt).all()

        monthly_data = {}
        for month, total in rev_results:
            if month:
                monthly_data[month] = {'revenue': Decimal(str(total or 0)), 'costs': Decimal('0.00'), 'profit': Decimal(str(total or 0))}

        cost_month_expr = func.to_char(Invoice.created_at, 'YYYY-MM')
        cost_stmt = db.select(
            cost_month_expr.label('month'),
            func.sum(InvoiceItem.cost_price * InvoiceItem.quantity)
        ).join(Invoice, InvoiceItem.invoice_id == Invoice.id)\
         .join(Ticket, Invoice.ticket_id == Ticket.id)\
         .filter(Ticket.location_id == location_id)\
         .group_by(cost_month_expr)
        cost_results = db.session.execute(cost_stmt).all()

        for month, total in cost_results:
            if month:
                if month not in monthly_data:
                    monthly_data[month] = {'revenue': Decimal('0.00'), 'costs': Decimal('0.00'), 'profit': Decimal('0.00')}
                monthly_data[month]['costs'] = Decimal(str(total or 0))
                monthly_data[month]['profit'] = monthly_data[month]['revenue'] - monthly_data[month]['costs']

        return sorted([{'month': k, **v} for k, v in monthly_data.items()], key=lambda x: x['month'], reverse=True)

class DocumentService:
    @staticmethod
    def generate_invoice_pdf(ticket_id: int) -> Tuple[bool, Any]:
        """Handles receipt-style PDF generation"""
        # Optimization: Eager load relationships to prevent N+1 queries during PDF generation
        stmt = db.select(Ticket).options(
            joinedload(Ticket.customer),
            joinedload(Ticket.device),
            selectinload(Ticket.ticket_services).joinedload(TicketServiceBridge.service),
            selectinload(Ticket.invoices).selectinload(Invoice.items)
        ).where(Ticket.id == ticket_id)
        ticket = db.session.scalar(stmt)

        if not ticket:
            return False, _('Ticket not found')
        
        invoice = FinancialService.get_or_create_invoice(ticket_id)
        # Multi-tenancy: Fetch branding settings specific to the ticket's branch location
        shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=ticket.location_id))
        
        # UI Integrity: Ensure PDF matches the viewing admin's currency settings
        from flask_login import current_user
        # Safely get currency info from current user (PDF is generated in request context)
        user_currency = getattr(current_user, 'currency', 'USD')
        symbol = get_currency_symbol(user_currency, locale=get_locale())
        decimals = getattr(current_user, 'currency_decimals', None)
        if decimals is None: decimals = get_currency_precision(user_currency)

        buffer = io.BytesIO()
        page_width = 80 * mm
        item_count = len(ticket.ticket_services) + len(invoice.items)
        page_height = (60 + (item_count * 12) + 40) * mm
        
        doc = SimpleDocTemplate(buffer, pagesize=(page_width, page_height),
                                rightMargin=4*mm, leftMargin=4*mm, topMargin=5*mm, bottomMargin=5*mm)
        
        elements = []
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Heading2'], alignment=1, fontSize=14, spaceAfter=5, fontName='Helvetica-Bold')
        normal_style = ParagraphStyle('Normal', parent=styles['Normal'], fontSize=9, leading=11, fontName='Courier')
        bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=9, leading=11, fontName='Courier-Bold')
        small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=7, leading=9, alignment=1)
        
        # Branded Logo Support
        if shop_info and shop_info.logo_path:
            logo_path = os.path.join(current_app.config['UPLOAD_DIR'], 'logos', shop_info.logo_path)
            if os.path.exists(logo_path):
                img = Image(logo_path, width=25*mm, height=25*mm)
                img.hAlign = 'CENTER'
                elements.append(img)

        elements.append(Paragraph(shop_info.shop_name if shop_info else "Repair Shop", title_style))
        if shop_info:
            if shop_info.shop_address: elements.append(Paragraph(shop_info.shop_address, small_style))
            if shop_info.shop_phone: elements.append(Paragraph(f"{_('Tel:')} {shop_info.shop_phone}", small_style))
        
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph(f"<b>{_('Invoice:')}</b> {invoice.invoice_number}", normal_style))
        elements.append(Paragraph(f"<b>{_('Date:')}</b> {invoice.created_at.strftime('%d/%m/%Y %H:%M')}", normal_style))
        elements.append(Paragraph(f"<b>{_('Customer:')}</b> {ticket.customer.name}", normal_style))
        elements.append(Paragraph(f"<b>{_('Device:')}</b> {ticket.device.display}", normal_style))
        elements.append(Spacer(1, 2*mm))
        elements.append(Paragraph("." * 40, normal_style))
        
        data = [[_('Description'), _('Qty'), _('Total')]]
        for ts in ticket.ticket_services:
            data.append([_(ts.service.name), str(ts.quantity), f"{symbol}{ts.price_charged * ts.quantity:.{decimals}f}"])
        for item in invoice.items:
            data.append([item.description, str(item.quantity), f"{symbol}{item.total_price:.{decimals}f}"])
            
        table = Table(data, colWidths=[38*mm, 10*mm, 24*mm])
        table.setStyle(TableStyle([('FONTNAME', (0,0), (-1,-1), 'Courier'), ('FONTSIZE', (0,0), (-1,-1), 8), ('ALIGN', (1,0), (1,-1), 'CENTER'), ('ALIGN', (2,0), (2,-1), 'RIGHT'), ('LINEBELOW', (0,0), (-1,0), 0.5, colors.black)]))
        elements.append(table)
        elements.append(Paragraph("." * 40, normal_style))
        elements.append(Spacer(1, 2*mm))
        elements.append(Paragraph(f"<b>{_('Grand Total:')}</b> {symbol}{invoice.total_amount:.{decimals}f}", normal_style))
        elements.append(Paragraph(f"<b>{_('Paid:')}</b> {symbol}{invoice.full_payment_received:.{decimals}f}", normal_style))
        elements.append(Paragraph(f"<b>{_('Balance Due:')}</b> {symbol}{invoice.remaining_balance:.{decimals}f}", bold_style))
        elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph(_("Thank you for your business!"), small_style))
        
        doc.build(elements)
        buffer.seek(0)
        return True, buffer