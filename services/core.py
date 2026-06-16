import os
import html
from datetime import datetime
from decimal import Decimal
import uuid
from typing import Tuple, Any, Optional, Dict, List
from flask import current_app
from flask_babel import _, get_locale
from sqlalchemy import func, or_, desc
from babel.numbers import get_currency_symbol, get_currency_precision, format_currency, format_decimal
from sqlalchemy.orm import joinedload, selectinload
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from flask_login import current_user
import io
from models import db, Ticket, Payment, Note, Invoice, Service, SparePart, InvoiceItem, TicketService as TicketServiceBridge, Customer, Device, ShopSetting, User

class FinancialService:
    @staticmethod
    def get_or_create_invoice(ticket_id: Optional[int] = None, customer_id: Optional[int] = None, location_id: Optional[int] = None) -> Invoice:
        """Ensures a draft or active invoice exists for the ticket"""
        invoice = db.session.scalar(db.select(Invoice).where(Invoice.ticket_id == ticket_id)) if ticket_id else None
        if not invoice:
            # SCALABILITY: Inherit attributes from ticket to ensure multi-tenancy integrity
            if ticket_id:
                ticket = db.session.get(Ticket, ticket_id)
                if ticket:
                    customer_id = ticket.customer_id
                    location_id = ticket.location_id

            invoice = Invoice(
                invoice_number=f"INV-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
                ticket_id=ticket_id,
                customer_id=customer_id,
                location_id=location_id,
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
        
        db.session.refresh(invoice)
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
            .where(Invoice.ticket_id == ticket_id)
        ) or Decimal('0.00')

        ticket.actual_cost = wholesale_sum
        db.session.flush()

    @staticmethod
    def void_payment(payment_id: int, user_id: int) -> Tuple[bool, str]:
        """Voids a payment record and re-evaluates the associated invoice status"""
        payment = db.session.execute(db.select(Payment).where(Payment.id == payment_id).options(joinedload(Payment.invoice))).scalar()
        if not payment:
            return False, _('Payment not found')

        # SECURITY & INTEGRITY: Multi-tenancy check
        user = db.session.get(User, user_id)
        if not user or not user.is_active:
            return False, _('Authorized user required')

        if not user.is_superuser:
            if payment.invoice and payment.invoice.location_id != user.location_id:
                return False, _('Access denied')

        invoice_id = payment.invoice_id
        db.session.delete(payment)
        db.session.flush()

        if invoice_id:
            FinancialService.sync_invoice_status(invoice_id)
        return True, _('Payment voided successfully')

    @staticmethod
    def record_payment(invoice_id: int, amount: Decimal, method: str, reference: str, user_id: int, ticket_id: Optional[int] = None) -> Tuple[bool, Any]:
        """Records a payment, updates invoice status, and creates an automated note"""
        invoice = db.session.get(Invoice, invoice_id)
        if not invoice:
            return False, _('Invoice not found')

        user = db.session.get(User, user_id)
        if not user or not user.is_active:
            return False, _('Authorized user required')

        if not user.is_superuser and invoice.location_id != user.location_id:
            return False, _('Access denied')

        payment = Payment(
            ticket_id=ticket_id or invoice.ticket_id,
            invoice_id=invoice.id,
            user_id=user_id,
            amount=amount,
            payment_method=method,
            transaction_reference=reference,
            paid_at=datetime.now()
        )
        db.session.add(payment)
        db.session.flush()

        FinancialService.sync_invoice_status(invoice.id)

        # INTEGRITY: Use shop settings for currency formatting in automated notes.
        # Robust lookup: Try specific branch settings first, fallback to global settings.
        shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=invoice.location_id))
        if not shop_info:
            shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=None))
        currency = shop_info.currency if shop_info else (user.currency or 'USD')

        note_type = _('Payment Received') if amount >= 0 else _('Change Given / Refund')
        note_content = _('%(type)s: %(amount)s. Method: %(method)s. Ref: %(ref)s', 
                         type=note_type, amount=format_currency(abs(amount), currency, locale=get_locale()), method=method, ref=reference)

        if ticket_id or invoice.ticket_id:
            note = Note(
                ticket_id=ticket_id or invoice.ticket_id,
                user_id=user_id,
                note_type=note_type,
                content=note_content,
                is_internal=True,
                created_at=datetime.now()
            )
            db.session.add(note)
        return True, payment

    @staticmethod
    def get_ticket_profitability(ticket_id: int) -> Dict[str, Any]:
        """Calculates revenue, wholesale cost, and net profit for a specific ticket"""
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            return {}

        # SECURITY: Multi-tenancy and Authentication check
        if not current_user.is_authenticated or not current_user.is_active:
            return {}
        if not current_user.is_superuser and ticket.location_id != current_user.location_id:
            # Silent return for security to avoid leaking existence of ticket
            return {} 

        # INTEGRITY: Use invoice total for accurate revenue reporting
        invoice = FinancialService.get_or_create_invoice(ticket_id)
        revenue = invoice.total_amount
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
        """Backward compatibility wrapper for ticket-based services"""
        # SECURITY: Preliminary check to avoid orphaned invoice creation
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            return False, _('Ticket not found')
        if not current_user.is_authenticated or not current_user.is_active:
            return False, _('Authorized user required')
        if not current_user.is_superuser and ticket.location_id != current_user.location_id:
            return False, _('Access denied')

        invoice = FinancialService.get_or_create_invoice(ticket_id=ticket_id)
        return InventoryService.add_service_to_invoice(invoice.id, service_id, quantity)

    @staticmethod
    def add_service_to_invoice(invoice_id: int, service_id: int, quantity: int) -> Tuple[bool, Any]:
        """Attaches a catalog service to a ticket and updates the invoice"""
        if quantity <= 0:
            return False, _('Quantity must be greater than zero')

        service = db.session.get(Service, service_id)
        if not service or not service.is_active:
            return False, _('Service not found or inactive')
        
        invoice = db.session.get(Invoice, invoice_id)
        if not invoice:
             return False, _('Invoice not found')
        
        # SECURITY: Multi-tenancy and Permission check
        if not current_user.is_authenticated or not current_user.is_active:
            return False, _('Authentication required')
        if not current_user.is_superuser and invoice.location_id != current_user.location_id:
            return False, _('Access denied')

        # Integrity: Ensure catalog item belongs to the same location as the invoice
        if service.location_id != invoice.location_id:
            return False, _('Service does not belong to this location')
        
        if invoice.ticket_id:
            ts = TicketServiceBridge(
                ticket_id=invoice.ticket_id,
                service_id=service_id,
                quantity=quantity,
                price_charged=service.price
            )
            db.session.add(ts)
            result = ts
        else:
            # For POS sales without tickets, services are recorded as line items
            result = InvoiceItem(
                invoice_id=invoice.id,
                description=service.name,
                quantity=quantity,
                cost_price=Decimal('0.00'),
                unit_price=service.price,
                total_price=service.price * quantity
            )
            db.session.add(result)

        db.session.flush()
        db.session.refresh(invoice)
        invoice.calculate_total()
        db.session.flush()
        if invoice.ticket_id:
            FinancialService.sync_ticket_summaries(invoice.ticket_id)
        FinancialService.sync_invoice_status(invoice.id)
        return True, result

    @staticmethod
    def add_part_to_ticket(ticket_id: int, part_id: Optional[int], manual_name: Optional[str], 
                           quantity: int, price: Optional[Decimal], cost: Optional[Decimal]) -> Tuple[bool, Any]:
        """Backward compatibility wrapper for ticket-based parts"""
        # SECURITY: Preliminary check
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            return False, _('Ticket not found')
        if not current_user.is_authenticated or not current_user.is_active:
            return False, _('Authorized user required')
        if not current_user.is_superuser and ticket.location_id != current_user.location_id:
            return False, _('Access denied')

        invoice = FinancialService.get_or_create_invoice(ticket_id=ticket_id)
        return InventoryService.add_part_to_invoice(invoice.id, part_id, manual_name, quantity, price, cost)

    @staticmethod
    def add_part_to_invoice(invoice_id: int, part_id: Optional[int], manual_name: Optional[str], 
                           quantity: int, price: Optional[Decimal], cost: Optional[Decimal]) -> Tuple[bool, Any]:
        """Adds an inventory or manual part to an invoice and updates totals"""
        if quantity <= 0:
            return False, _('Quantity must be greater than zero')

        invoice = db.session.get(Invoice, invoice_id)
        if not invoice:
            return False, _('Invoice not found')

        # SECURITY: User permission check for the target invoice
        if not current_user.is_authenticated or not current_user.is_active:
            return False, _('Authentication required')
        if not current_user.is_superuser and invoice.location_id != current_user.location_id:
            return False, _('Access denied')

        description = ""
        item_price = Decimal('0.00')
        item_cost = Decimal('0.00')
        spare_part_id = None

        if part_id:
            # Concurrency: Lock the row for update to ensure stock integrity
            part = db.session.execute(db.select(SparePart).where(SparePart.id == part_id).with_for_update()).scalar()
            if not part or not part.is_active:
                return False, _('Part not found or inactive')
            
            # SECURITY & Integrity: Cross-location inventory check
            if part.location_id != invoice.location_id:
                return False, _('Part does not belong to this location')

            description = part.name
            item_price = price if price is not None else part.selling_price
            item_cost = part.cost or Decimal('0.00')
            spare_part_id = part.id
            
            # Inventory Management: Decrement stock
            if part.stock_quantity < quantity:
                return False, _('Insufficient stock for "%(name)s". Current: %(qty)s', name=part.name, qty=part.stock_quantity)
            part.stock_quantity -= quantity

        elif manual_name:
            description = manual_name
            item_price = price if price is not None else Decimal('0.00')
            item_cost = cost if cost is not None else Decimal('0.00')
        
        if not description:
            return False, _('Invalid part details')

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
        db.session.refresh(invoice)
        invoice.calculate_total()
        db.session.flush()
        if invoice.ticket_id:
            FinancialService.sync_ticket_summaries(invoice.ticket_id)
        FinancialService.sync_invoice_status(invoice.id)
        return True, item

    @staticmethod
    def remove_service(ticket_id: Optional[int], ts_id: int) -> Tuple[bool, Optional[str]]:
        """Removes a service (either ticket-linked or standalone) and updates the invoice total"""
        # Try finding in TicketServiceBridge first if ticket context exists
        if ticket_id:
            ts = db.session.get(TicketServiceBridge, ts_id)
            if ts and ts.ticket_id == ticket_id:                
                invoice = db.session.scalar(db.select(Invoice).where(Invoice.ticket_id == ticket_id))
                
                # SECURITY: Robust multi-tenancy check
                if invoice:
                    if not current_user.is_authenticated or not current_user.is_active:
                        return False, _('Authentication required')
                    if not current_user.is_superuser and invoice.location_id != current_user.location_id:
                        return False, _('Access denied')

                db.session.delete(ts)
                db.session.flush()
                if invoice:
                    db.session.refresh(invoice)
                    invoice.calculate_total()
                    db.session.flush()
                    FinancialService.sync_invoice_status(invoice.id)
                FinancialService.sync_ticket_summaries(ticket_id)
                return True, None
        
        # Fallback to InvoiceItem (Standalone POS service or legacy data)
        item = db.session.get(InvoiceItem, ts_id)
        if not item:
            return False, _('Service entry not found')

        # INTEGRITY: Ensure we are not accidentally removing a part via the service removal route
        if item.spare_part_id is not None:
            return False, _('This item is a part, not a service.')

        invoice = item.invoice
        # SECURITY: Multi-tenancy check
        if not invoice:
            return False, _('Invoice consistency error')
            
        if not current_user.is_authenticated or not current_user.is_active:
            return False, _('Authentication required')
        if not current_user.is_superuser and invoice.location_id != current_user.location_id:
            return False, _('Access denied')

        db.session.delete(item)
        db.session.flush()
        if invoice:
            db.session.refresh(invoice)
            invoice.calculate_total()
            db.session.flush()
            FinancialService.sync_invoice_status(invoice.id)
            if invoice.ticket_id:
                FinancialService.sync_ticket_summaries(invoice.ticket_id)
        return True, None

    @staticmethod
    def remove_part(item_id: int) -> Tuple[bool, Optional[str]]:
        """Removes a part, restores inventory stock, and updates invoice"""
        item = db.session.get(InvoiceItem, item_id)
        if not item:
            return False, _('Part entry not found')

        invoice = item.invoice
        # SECURITY: Multi-tenancy check
        if not invoice:
            return False, _('Invoice consistency error')

        if not current_user.is_authenticated or not current_user.is_active:
            return False, _('Authentication required')
        if not current_user.is_superuser and invoice.location_id != current_user.location_id:
            return False, _('Access denied')

        # Inventory Management: Restore stock if linked to a catalog part
        if item.spare_part_id:
            # Integrity: Lock the part row for update to prevent race conditions during stock restoration
            part = db.session.execute(db.select(SparePart).where(SparePart.id == item.spare_part_id).with_for_update()).scalar()
            if part:
                part.stock_quantity += item.quantity

        ticket_id = invoice.ticket_id
        db.session.delete(item)
        db.session.flush()
        db.session.refresh(invoice)
        invoice.calculate_total()
        db.session.flush()
        FinancialService.sync_invoice_status(invoice.id)
        FinancialService.sync_ticket_summaries(ticket_id)
        return True, None

class CustomerService:
    @staticmethod
    def create_customer(name: str, phone: str, address: str = '', location_id: Optional[int] = None) -> Tuple[bool, Any]:
        """Standardized customer creation logic used by both forms and AJAX"""
        if not name or not phone:
            return False, _('Name and phone are required')
            
        if not current_user.is_authenticated or not current_user.is_active:
            return False, _('Authorized user required')

        # SECURITY: Enforce multi-tenancy for non-superusers
        if current_user.is_authenticated and not current_user.is_superuser:
            location_id = current_user.location_id

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
            
        if not current_user.is_authenticated or not current_user.is_active:
            return False, _('Authorized user required')

        # SECURITY: Verify customer ownership
        customer = db.session.get(Customer, customer_id)
        if not customer:
            return False, _('Customer not found')
            
        if current_user.is_authenticated and not current_user.is_superuser:
            if customer.location_id != current_user.location_id:
                return False, _('Access denied')

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
        # SECURITY: Multi-tenancy check
        if not current_user.is_authenticated or not current_user.is_active:
            return []
        if not current_user.is_superuser and location_id != current_user.location_id:
            return []

        month_expr = func.to_char(Payment.paid_at, 'YYYY-MM')
        rev_stmt = db.select(
            month_expr.label('month'),
            func.sum(Payment.amount)
        ).join(Invoice, Payment.invoice_id == Invoice.id)\
         .where(Invoice.location_id == location_id)\
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
         .where(Invoice.location_id == location_id)\
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
        
        # SECURITY: Multi-tenancy check
        if not current_user.is_authenticated or not current_user.is_active:
            return False, _('Authentication required')
        if not current_user.is_superuser and ticket.location_id != current_user.location_id:
            return False, _('Access denied')

        invoice = FinancialService.get_or_create_invoice(ticket_id)
        invoice.calculate_total()
        
        # Multi-tenancy: Fetch branding settings. 
        # Robust lookup: Try specific branch settings first, fallback to global settings.
        shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=ticket.location_id))
        if not shop_info:
            shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=None))
        
        # INTEGRITY: Invoices must reflect the branch's specific currency settings 
        # rather than the individual preference of the staff member viewing the file.
        invoice_currency = (shop_info.currency if shop_info and shop_info.currency else None) or \
                          (getattr(current_user, 'currency', 'USD') if current_user and current_user.is_authenticated else 'USD')

        locale = get_locale()

        buffer = io.BytesIO()
        page_width = 80 * mm
        item_count = len(ticket.ticket_services) + len(invoice.items)
        page_height = (60 + (item_count * 12) + 40) * mm
        
        doc = SimpleDocTemplate(buffer, pagesize=(page_width, page_height),
                                rightMargin=4*mm, leftMargin=4*mm, topMargin=5*mm, bottomMargin=5*mm)
        
        elements = []
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Heading2'], alignment=1, fontSize=14, spaceAfter=5, fontName='Courier-Bold')
        normal_style = ParagraphStyle('Normal', parent=styles['Normal'], fontSize=9, leading=11, fontName='Courier')
        bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=9, leading=11, fontName='Courier-Bold')
        small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=7, leading=9, alignment=1, fontName='Courier')
        
        elements.append(Paragraph(html.escape(shop_info.shop_name if shop_info else _("Repair Shop")), title_style))
        # Use physical branch details from Location instead of global shop settings for contact info
        loc = ticket.location
        if loc:
            if loc.address: elements.append(Paragraph(html.escape(loc.address), small_style))
            if loc.phone: elements.append(Paragraph(f"{_('Tel:')} {html.escape(loc.phone)}", small_style))
        
        elements.append(Spacer(1, 3*mm))
        elements.append(Paragraph(f"<b>{_('Ticket:')}</b> {ticket.ticket_number}", normal_style))
        elements.append(Paragraph(f"<b>{_('Invoice:')}</b> {invoice.invoice_number}", normal_style))
        elements.append(Paragraph(f"<b>{_('Date:')}</b> {invoice.created_at.strftime('%d/%m/%Y %H:%M')}", normal_style))
        elements.append(Paragraph(f"<b>{_('Customer:')}</b> {html.escape(ticket.customer.name if ticket.customer else _('Walk-in'))}", normal_style))
        elements.append(Paragraph(f"<b>{_('Device:')}</b> {html.escape(ticket.device.display if ticket.device else _('N/A'))}", normal_style))
        elements.append(Spacer(1, 2*mm))
        elements.append(Paragraph("." * 35, normal_style))
        
        # Custom formatting to strictly follow decimal settings and enable text wrapping in cells
        precision = shop_info.currency_decimals if shop_info else 2
        pattern = "#,##0" + (("." + "0" * precision) if precision > 0 else "")
        symbol = get_currency_symbol(invoice_currency, locale=locale)
        
        def local_format(amt):
            return f"{symbol} {format_decimal(amt, format=pattern, locale=locale)}"

        table_cell_style = ParagraphStyle('TableCell', parent=normal_style, fontSize=8, leading=10)
        data = [[_('Description'), _('Qty'), _('Total')]]
        for ts in ticket.ticket_services:
            desc = Paragraph(html.escape(ts.service.name), table_cell_style)
            data.append([desc, str(ts.quantity), local_format(ts.price_charged * ts.quantity)])
        for item in invoice.items:
            desc = Paragraph(html.escape(item.description), table_cell_style)
            data.append([desc, str(item.quantity), local_format(item.total_price)])
            
        table = Table(data, colWidths=[38*mm, 10*mm, 24*mm])
        table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), 'Courier'),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('ALIGN', (1,0), (1,-1), 'CENTER'),
            ('ALIGN', (2,0), (2,-1), 'RIGHT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LINEBELOW', (0,0), (-1,0), 0.5, colors.black)
        ]))
        elements.append(table)
        elements.append(Paragraph("." * 35, normal_style))
        elements.append(Spacer(1, 2*mm))
        elements.append(Paragraph(f"<b>{_('Grand Total:')}</b> {local_format(invoice.total_amount)}", normal_style))
        elements.append(Paragraph(f"<b>{_('Paid:')}</b> {local_format(invoice.full_payment_received)}", normal_style))
        elements.append(Paragraph(f"<b>{_('Balance Due:')}</b> {local_format(invoice.remaining_balance)}", bold_style))
        elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph(_("Thank you!"), small_style))
        
        doc.build(elements)
        buffer.seek(0)
        return True, buffer