from datetime import datetime, timezone
from decimal import Decimal
import uuid
from typing import Tuple, Any, Optional, Dict, List
from flask import current_app
from flask_babel import _
from sqlalchemy import func, or_, desc
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import io
import json

from models import db, Ticket, PhaseLog, Payment, Note, Invoice, Service, SparePart, InvoiceItem, TicketService as TicketServiceBridge, Customer, Device, Location, ShopSetting, User

class FinancialService:
    @staticmethod
    def get_or_create_invoice(ticket_id: int) -> Invoice:
        """Ensures a draft or active invoice exists for the ticket"""
        invoice = Invoice.query.filter_by(ticket_id=ticket_id).first()
        if not invoice:
            invoice = Invoice(
                invoice_number=f"INV-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
                ticket_id=ticket_id,
                status='Draft'
            )
            db.session.add(invoice)
            db.session.flush()
        return invoice

    @staticmethod
    def record_payment(ticket_id: int, amount: Decimal, method: str, reference: str, user_id: int) -> Tuple[bool, Any]:
        """Records a payment, updates invoice status, and creates an automated note"""
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            return False, _('Ticket not found')

        payment = Payment(
            ticket_id=ticket.id,
            user_id=user_id,
            amount=amount,
            payment_method=method,
            transaction_reference=reference,
            paid_at=datetime.now(timezone.utc)
        )
        db.session.add(payment)
        db.session.flush()

        invoice = FinancialService.get_or_create_invoice(ticket_id)
        balance = invoice.remaining_balance
        if balance <= 0:
            invoice.status = 'Paid'
        elif balance < invoice.total_amount:
            invoice.status = 'Partial'

        symbol = current_app.jinja_env.globals.get('currency_symbol', '$')
        if callable(symbol): symbol = '$'

        note_type = _('Payment Received') if amount > 0 else _('Change Given / Refund')
        note_content = _('%(type)s: %(symbol)s%(amount)s. Method: %(method)s. Ref: %(ref)s', 
                         type=note_type, symbol=symbol, amount=abs(amount), method=method, ref=reference)

        note = Note(
            ticket_id=ticket.id,
            user_id=user_id,
            note_type=note_type,
            content=note_content,
            is_internal=True
        )
        db.session.add(note)
        return True, payment

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
            # TECHNICAL FIX: Prevent Race Condition using SELECT ... FOR UPDATE
            part = db.session.query(SparePart).filter_by(id=part_id).with_for_update().first()
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
        invoice.calculate_total()
        return True, item

    @staticmethod
    def remove_service(ticket_id: int, ts_id: int) -> Tuple[bool, Optional[str]]:
        """Removes a service and updates the invoice total"""
        ts = db.session.get(TicketServiceBridge, ts_id)
        if not ts:
            return False, _('Service entry not found')
            
        invoice = Invoice.query.filter_by(ticket_id=ticket_id).first()
        db.session.delete(ts)
        db.session.flush()
        
        if invoice:
            invoice.calculate_total()
        return True, None

    @staticmethod
    def remove_part(item_id: int) -> Tuple[bool, Optional[str]]:
        """Removes a part, restores inventory stock, and updates invoice"""
        item = db.session.get(InvoiceItem, item_id)
        if not item:
            return False, _('Part entry not found')

        # Inventory Management: Restore stock if linked to a catalog part
        if item.spare_part_id:
            part = db.session.get(SparePart, item.spare_part_id)
            if part:
                part.stock_quantity += item.quantity

        invoice = item.invoice
        db.session.delete(item)
        db.session.flush()
        invoice.calculate_total()
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
    def get_financial_analysis() -> List[Dict[str, Any]]:
        """Aggregates revenue and costs by month for financial reporting"""
        rev_results = db.session.query(
            func.to_char(Payment.paid_at, 'YYYY-MM').label('month'),
            func.sum(Payment.amount)
        ).group_by('month').all()

        monthly_data = {}
        for month, total in rev_results:
            if month:
                monthly_data[month] = {'revenue': Decimal(str(total or 0)), 'costs': Decimal('0.00'), 'profit': Decimal(str(total or 0))}

        cost_results = db.session.query(
            func.to_char(Invoice.created_at, 'YYYY-MM').label('month'),
            func.sum(InvoiceItem.cost_price * InvoiceItem.quantity)
        ).join(Invoice, InvoiceItem.invoice_id == Invoice.id).group_by('month').all()

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
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket or not ticket.invoices:
            return False, _('Invoice not found')
        
        invoice = ticket.invoices[0]
        shop_info = ShopSetting.query.first()
        symbol = current_app.jinja_env.globals.get('currency_symbol', '$')
        decimals = current_app.jinja_env.globals.get('currency_decimals', 2)

        buffer = io.BytesIO()
        page_width = 80 * mm
        item_count = len(ticket.ticket_services) + len(invoice.items)
        page_height = (80 + (item_count * 12) + 80) * mm
        
        doc = SimpleDocTemplate(buffer, pagesize=(page_width, page_height),
                                rightMargin=2*mm, leftMargin=2*mm, topMargin=5*mm, bottomMargin=5*mm)
        
        elements = []
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Heading2'], alignment=1, fontSize=12, spaceAfter=5)
        normal_style = ParagraphStyle('Normal', parent=styles['Normal'], fontSize=8, leading=10)
        bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=8, leading=10, fontName='Helvetica-Bold')
        small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=7, leading=9, alignment=1)
        
        elements.append(Paragraph(shop_info.shop_name if shop_info else "Repair Shop", title_style))
        if shop_info:
            if shop_info.shop_address: elements.append(Paragraph(shop_info.shop_address, small_style))
            if shop_info.shop_phone: elements.append(Paragraph(f"{_('Tel:')} {shop_info.shop_phone}", small_style))
        
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph(f"<b>{_('Invoice:')}</b> {invoice.invoice_number}", normal_style))
        elements.append(Paragraph(f"<b>{_('Date:')}</b> {invoice.created_at.strftime('%Y-%m-%d %H:%M')}", normal_style))
        elements.append(Paragraph(f"<b>{_('Customer:')}</b> {ticket.customer.name}", normal_style))
        elements.append(Paragraph(f"<b>{_('Device:')}</b> {ticket.device.display}", normal_style))
        elements.append(Spacer(1, 2*mm))
        elements.append(Paragraph("-" * 55, normal_style))
        
        data = [[_('Description'), _('Qty'), _('Total')]]
        for ts in ticket.ticket_services:
            data.append([_(ts.service.name), str(ts.quantity), f"{symbol}{'%.*f'|format(decimals, ts.price_charged * ts.quantity)}"])
        for item in invoice.items:
            data.append([item.description, str(item.quantity), f"{symbol}{'%.*f'|format(decimals, item.total_price)}"])
            
        table = Table(data, colWidths=[45*mm, 10*mm, 21*mm])
        table.setStyle(TableStyle([('FONTSIZE', (0,0), (-1,-1), 7), ('ALIGN', (1,0), (1,-1), 'CENTER'), ('ALIGN', (2,0), (2,-1), 'RIGHT'), ('LINEBELOW', (0,0), (-1,0), 0.5, colors.black)]))
        elements.append(table)
        elements.append(Paragraph("-" * 55, normal_style))
        elements.append(Spacer(1, 2*mm))
        elements.append(Paragraph(f"<b>{_('Grand Total:')}</b> {symbol}{'%.*f'|format(decimals, invoice.total_amount)}", normal_style))
        elements.append(Paragraph(f"<b>{_('Paid:')}</b> {symbol}{'%.*f'|format(decimals, invoice.full_payment_received)}", normal_style))
        elements.append(Paragraph(f"<b>{_('Balance Due:')}</b> {symbol}{'%.*f'|format(decimals, invoice.remaining_balance)}", bold_style))
        elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph(_("Thank you for your business!"), small_style))
        
        doc.build(elements)
        buffer.seek(0)
        return True, buffer

class BackupService:
    @staticmethod
    def get_system_logical_data() -> Dict[str, Any]:
        """Prepares a dictionary of all critical system data for export"""
        return {
            'locations': [{
                'id': l.id, 'name': l.name, 'address': l.address,
                'created_at': l.created_at.isoformat() if l.created_at else None
            } for l in Location.query.all()],
            'customers': [{
                'id': c.id, 'name': c.name, 'phone': c.phone, 'address': c.address, 
                'created_at': c.created_at.isoformat() if c.created_at else None
            } for c in Customer.query.all()],
            'devices': [{
                'id': d.id, 'customer_id': d.customer_id, 'device_type': d.device_type, 
                'brand': d.brand, 'model_number': d.model_number, 'serial_number': d.serial_number,
                'created_at': d.created_at.isoformat() if d.created_at else None
            } for d in Device.query.all()],
            'tickets': [{
                'id': t.id, 'ticket_number': t.ticket_number, 'customer_id': t.customer_id, 
                'current_phase': t.current_phase, 'estimated_cost': str(t.estimated_cost),
                'actual_cost': str(t.actual_cost), 'created_at': t.created_at.isoformat() if t.created_at else None
            } for t in Ticket.query.all()],
            'shop_settings': [{
                'shop_name': s.shop_name, 'shop_address': s.shop_address,
                'shop_phone': s.shop_phone, 'shop_email': s.shop_email,
                'setup_completed': s.setup_completed
            } for s in ShopSetting.query.all()]
        }