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
from reportlab.lib.pagesizes import A4
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
        include_tax = True
        if not invoice:
            # SCALABILITY: Inherit attributes from ticket to ensure multi-tenancy integrity
            if ticket_id:
                ticket = db.session.get(Ticket, ticket_id)
                if ticket:
                    customer_id = ticket.customer_id
                    location_id = ticket.location_id
                    include_tax = ticket.include_tax

            invoice = Invoice(
                invoice_number=f"INV-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
                ticket_id=ticket_id,
                customer_id=customer_id,
                location_id=location_id,
                status='Draft',
                include_tax=include_tax
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
        
        old_status = invoice.status
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

        # INTEGRITY: Synchronize Loyalty Point balance on Paid state transition
        # Accounts for both points earned on the purchase and points redeemed for discounts
        if invoice.customer:
            point_delta = (invoice.loyalty_points_earned or 0) - (invoice.loyalty_points_used or 0)
            if invoice.status == 'Paid' and old_status != 'Paid':
                invoice.customer.loyalty_points += point_delta
            elif old_status == 'Paid' and invoice.status != 'Paid':
                invoice.customer.loyalty_points -= point_delta

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
            if not user.has_permission('process_payments'):
                return False, _('Permission denied')

        invoice_id = payment.invoice_id
        ticket_id = payment.ticket_id
        amount = payment.amount
        method = payment.payment_method

        db.session.delete(payment)
        db.session.flush()

        if ticket_id:
            note = Note(
                ticket_id=ticket_id,
                user_id=user_id,
                note_type=_('Payment Voided'),
                content=_('Payment of %(amount)s (%(method)s) was voided.', amount=format_currency(abs(amount), user.currency or 'USD', locale=get_locale()), method=_(method)),
                is_internal=True
            )
            db.session.add(note)

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

        if not user.is_superuser:
            if invoice.location_id != user.location_id:
                return False, _('Access denied')
            if not user.has_permission('process_payments'):
                return False, _('Permission denied')

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
        if not shop_info:
            shop_info = db.session.scalar(db.select(ShopSetting).limit(1))
        currency = shop_info.currency if shop_info else (user.currency or 'USD')

        note_type = _('Payment Received') if amount >= 0 else _('Change Given / Refund')
        note_content = _('%(type)s: %(amount)s. Method: %(method)s. Ref: %(ref)s', 
                         type=note_type, amount=format_currency(abs(amount), currency, locale=get_locale()), method=_(method), ref=reference)

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
        if not current_user.is_superuser:
            if ticket.location_id != current_user.location_id:
                # Silent return for security to avoid leaking existence of ticket
                return {} 
            if not current_user.has_permission('view_reports'):
                return {}

        # INTEGRITY: Use invoice total for accurate revenue reporting
        invoice = FinancialService.get_or_create_invoice(ticket_id)
        # Net Revenue: Gross subtotal minus all applied discounts
        revenue = invoice.total_amount - invoice.tax_amount
        cost = ticket.actual_cost  # Synced wholesale cost
        profit = revenue - cost

        return {
            'revenue': revenue,
            'cost': cost,
            'profit': profit,
            'margin_percentage': (profit / revenue * 100) if revenue > 0 else 0
        }

    @staticmethod
    def get_invoice_summary_json(invoice: Invoice) -> Dict[str, Any]:
        """Generates consistent financial summary data for dynamic UI updates"""
        shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=invoice.location_id)) or \
                    db.session.scalar(db.select(ShopSetting).filter_by(location_id=None)) or \
                    db.session.scalar(db.select(ShopSetting).limit(1))
        currency_symbol = shop_info.currency_symbol if shop_info else '$'
        currency_decimals = shop_info.currency_decimals if shop_info else 2
        points_per = shop_info.loyalty_points_per_currency if shop_info else Decimal('1.00')
        est_points = invoice.subtotal_amount * points_per if shop_info and shop_info.enable_loyalty_points else 0

        return {
            'success': True,
            'subtotal_amount': f"{currency_symbol}{invoice.subtotal_amount:.{currency_decimals}f}",
            'tax_amount': f"{currency_symbol}{invoice.tax_amount:.{currency_decimals}f}",
            'discount_amount': f"-{currency_symbol}{invoice.discount_amount:.{currency_decimals}f}",
            'loyalty_discount': f"-{currency_symbol}{invoice.loyalty_discount_amount:.{currency_decimals}f}",
            'total_amount': f"{currency_symbol}{invoice.total_amount:.{currency_decimals}f}",
            'balance_due': f"{currency_symbol}{invoice.remaining_balance:.{currency_decimals}f}",
            'est_points': int(est_points),
            'tax_rate': float(invoice.tax_info['rate']),
            'include_tax': invoice.include_tax
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
        if not current_user.is_superuser:
            if invoice.location_id != current_user.location_id:
                return False, _('Access denied')

            # Determine correct permission based on context
            perm = 'process_sales' if not invoice.ticket_id else 'add_service'
            if not current_user.has_permission(perm):
                return False, _('Permission denied')

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
        if not current_user.is_superuser:
            if invoice.location_id != current_user.location_id:
                return False, _('Access denied')

            # Determine correct permission based on context
            perm = 'process_sales' if not invoice.ticket_id else 'add_part'
            if not current_user.has_permission(perm):
                return False, _('Permission denied')

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
                    
                    if not current_user.is_superuser and \
                       (invoice.location_id != current_user.location_id or \
                        ticket_id != ts.ticket_id):
                        return False, _('Access denied')
                    if not current_user.has_permission('remove_service'):
                        return False, _('Permission denied')

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
        if not current_user.is_superuser:
            if invoice.location_id != current_user.location_id or item.invoice_id != invoice.id:
                return False, _('Access denied')
            
            perm = 'process_sales' if not invoice.ticket_id else 'remove_service'
            if not current_user.has_permission(perm):
                return False, _('Permission denied')

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
        if not current_user.is_superuser:
            if invoice.location_id != current_user.location_id:
                return False, _('Access denied')
            
            perm = 'process_sales' if not invoice.ticket_id else 'remove_part'
            if not current_user.has_permission(perm):
                return False, _('Permission denied')

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

        # SECURITY: Enforce multi-tenancy and granular permission for non-superusers
        if not current_user.is_superuser:
            if location_id and location_id != current_user.location_id:
                return False, _('Access denied')
            if not current_user.has_permission('create_customer'):
                return False, _('Permission denied')
            location_id = current_user.location_id

        # INTEGRITY: Check for duplicates using the blind index before creation
        phone_hash = Customer.get_search_hash(phone)
        if phone_hash:
            exists = db.session.scalar(db.select(Customer.id).where(
                Customer.phone_hash == phone_hash,
                Customer.location_id == location_id
            ))
            if exists:
                return False, _('A customer with this phone number already exists.')

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
            
        if not current_user.is_superuser:
            if customer.location_id != current_user.location_id:
                return False, _('Access denied')
            if not current_user.has_permission('create_device'):
                return False, _('Permission denied')

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
    def get_financial_analysis(location_id: Optional[int]) -> List[Dict[str, Any]]:
        """Aggregates revenue and costs by month for financial reporting"""
        # SECURITY: Multi-tenancy check
        if not current_user.is_authenticated or not current_user.is_active:
            return []
        
        if not current_user.is_superuser and location_id != current_user.location_id:
            return []
        
        if not current_user.has_permission('view_reports'):
            return []

        loc_filter = (Invoice.location_id == location_id) if location_id else True
        month_expr = func.to_char(Payment.paid_at, 'YYYY-MM')
        
        # INTEGRITY: Select the objects to access Python properties safely.
        # Optimization: Eager load ticket and items to prevent N+1 queries during property access.
        rev_stmt = db.select(
            month_expr.label('month'),
            Payment,
            Invoice
        ).join(Invoice, Payment.invoice_id == Invoice.id)\
         .options(joinedload(Invoice.ticket).selectinload(Ticket.ticket_services), selectinload(Invoice.items))\
         .where(loc_filter)
        
        rev_results = db.session.execute(rev_stmt).all()

        monthly_data = {}
        for month, payment, invoice in rev_results:
            if month:
                # Calculate net portion of payment based on the invoice's actual tax proportion.
                # This respects historical tax rates and transaction-specific discounts.
                if invoice.total_amount and invoice.total_amount > 0:
                    tax_ratio = invoice.tax_amount / invoice.total_amount
                    net_payment = payment.amount * (1 - tax_ratio)
                else:
                    net_payment = payment.amount
                
                if month not in monthly_data:
                    monthly_data[month] = {'revenue': Decimal('0.00'), 'costs': Decimal('0.00'), 'profit': Decimal('0.00')}
                
                net_revenue = Decimal(str(net_payment or 0))
                monthly_data[month]['revenue'] += net_revenue
                monthly_data[month]['profit'] += net_revenue

        cost_month_expr = func.to_char(Invoice.created_at, 'YYYY-MM')
        cost_stmt = db.select(
            cost_month_expr.label('month'),
            func.sum(InvoiceItem.cost_price * InvoiceItem.quantity)
        ).join(Invoice, InvoiceItem.invoice_id == Invoice.id)\
         .where(loc_filter)\
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
    def generate_invoice_pdf(invoice_id: int, doc_type: str = 'invoice') -> Tuple[bool, Any]:
        """Handles receipt-style PDF generation"""
        # INTEGRITY: Fetch the invoice as the primary document source to support both Repairs and POS
        stmt = db.select(Invoice).options(
            joinedload(Invoice.customer),
            joinedload(Invoice.location),
            joinedload(Invoice.ticket).joinedload(Ticket.device),
            joinedload(Invoice.ticket).joinedload(Ticket.customer),
            joinedload(Invoice.ticket).selectinload(Ticket.ticket_services).joinedload(TicketServiceBridge.service),
            selectinload(Invoice.items).joinedload(InvoiceItem.part),
            selectinload(Invoice.payments)
        ).where(Invoice.id == invoice_id)
        invoice = db.session.scalar(stmt)

        if not invoice:
            return False, _('Invoice not found')

        ticket = invoice.ticket

        # SECURITY: Multi-tenancy check
        if not current_user.is_authenticated or not current_user.is_active:
            return False, _('Authentication required')
        if not current_user.is_superuser:
            if invoice.location_id != current_user.location_id:
                return False, _('Access denied')
            # Check either view_ticket or process_sales (for POS)
            if not current_user.has_permission('view_ticket') and not current_user.has_permission('process_sales'):
                return False, _('Permission denied')

        # INTEGRITY: Avoid recalculation for archived/locked tickets to preserve historical tax/price accuracy
        if ticket and ticket.current_phase != 'Already Taken' and not ticket.is_archived:
            invoice.calculate_total()
        
        # Multi-tenancy: Fetch branding settings. 
        # Robust lookup: Try specific branch settings first, fallback to global settings.
        shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=invoice.location_id))
        if not shop_info:
            shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=None))
        if not shop_info:
            shop_info = db.session.scalar(db.select(ShopSetting).limit(1))

        # INTEGRITY: Invoices must reflect the branch's specific currency settings 
        # rather than the individual preference of the staff member viewing the file.
        invoice_currency = (shop_info.currency if shop_info and shop_info.currency else None) or \
                          (getattr(current_user, 'currency', 'USD') if current_user and current_user.is_authenticated else 'USD')

        brand_hex = shop_info.brand_color if shop_info and shop_info.brand_color else '#0d6efd'
        brand_color = colors.HexColor(brand_hex)

        locale = get_locale()

        buffer = io.BytesIO()

        pdf_format = shop_info.pdf_page_format if shop_info else 'thermal'
        if pdf_format == 'a4':
            pagesize = A4
            left_margin = right_margin = 15 * mm
            top_margin = bottom_margin = 15 * mm
            col_1_width, col_2_width, col_3_width = 115 * mm, 25 * mm, 40 * mm
            meta_col_widths = [45*mm, 135*mm]
            font_name = 'Helvetica'
        else:
            page_width = 80 * mm
            ts_count = len(ticket.ticket_services) if ticket else 0
            item_count = ts_count + len(invoice.items)
            payment_count = len(invoice.payments) if invoice else 0
            # SCALABILITY: Dynamic height calculation for thermal rolls
            page_height = (140 + (item_count * 12) + (payment_count * 8) + 120) * mm
            pagesize = (page_width, page_height)
            left_margin = right_margin = 3 * mm
            top_margin = bottom_margin = 5 * mm
            col_1_width, col_2_width, col_3_width = 44 * mm, 8 * mm, 20 * mm 
            meta_col_widths = [22*mm, 52*mm]
            font_name = 'Helvetica'
        
        doc = SimpleDocTemplate(buffer, pagesize=pagesize,
                                rightMargin=right_margin, leftMargin=left_margin, 
                                topMargin=top_margin, bottomMargin=bottom_margin)
        
        elements = []
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle('Title', parent=styles['Heading2'], alignment=1, fontSize=11, spaceAfter=1, fontName=f'{font_name}-Bold', textColor=brand_color)
        header_style = ParagraphStyle('Header', parent=styles['Heading1'], alignment=1, fontSize=16, spaceAfter=5, fontName=f'{font_name}-Bold', textColor=brand_color) # Main title, keep large
        normal_style = ParagraphStyle('Normal', parent=styles['Normal'], fontSize=8.5, leading=11, fontName=font_name) 
        small_bold_style = ParagraphStyle('SmallBold', parent=styles['Normal'], fontSize=7.5, leading=10, fontName=f'{font_name}-Bold')
        bold_style = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=9, leading=11, fontName=f'{font_name}-Bold', textColor=brand_color) # Keep 9pt for specific bold elements
        small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=7, leading=9, alignment=1, fontName=font_name) 
        small_left_style = ParagraphStyle('SmallLeft', parent=styles['Normal'], fontSize=7, leading=9, alignment=0, fontName=font_name)
        note_title_style = ParagraphStyle('NoteTitle', parent=styles['Normal'], fontSize=8, leading=10, fontName=f'{font_name}-Bold', spaceBefore=3)
        paid_stamp_style = ParagraphStyle('PaidStamp', parent=styles['Normal'], fontName=f'{font_name}-Bold', fontSize=36, textColor=colors.Color(0.15, 0.65, 0.27, alpha=0.15), alignment=1)
        
        if doc_type == 'receipt':
            doc_label = (shop_info.receipt_label if shop_info and shop_info.receipt_label else _('RECEIPT')).upper()
            # PAID watermark for receipt context
            elements.append(Paragraph(_('PAID'), paid_stamp_style))
            elements.append(Spacer(1, -10*mm)) # Overlap slightly for visual effect
        elif doc_type == 'job_sheet':
            doc_label = _('JOB SHEET').upper()
        else:
            doc_label = (shop_info.invoice_label if shop_info and shop_info.invoice_label else _('INVOICE')).upper()

        # Document Header
        if pdf_format == 'a4':
            # Improvement: Multi-column header for A4 format
            header_left = []
            if shop_info and shop_info.logo_path and shop_info.show_logo_on_docs:
                logo_path = os.path.join(current_app.config['LOGOS_DIR'], shop_info.logo_path)
                if os.path.exists(logo_path):
                    try:
                        # Use kind='proportional' to ensure the logo isn't stretched
                        img = Image(logo_path, width=30*mm, height=30*mm, kind='proportional')
                        img.hAlign = 'LEFT'
                        header_left.append(img)
                    except: pass
            
            header_left.append(Paragraph(html.escape(shop_info.shop_name if (shop_info and shop_info.shop_name) else _("Repair Shop")), title_style))
            
            loc = invoice.location or (ticket.location if ticket else None)
            shop_email = (loc.email if loc and loc.email else None) or (shop_info.shop_email if shop_info else None)
            shop_phone = (loc.phone if loc and loc.phone else None) or (shop_info.shop_phone if shop_info else None)
            shop_address = (loc.address if loc and loc.address else None) or (shop_info.shop_address if shop_info else None)
            
            if loc and loc.name and shop_info and loc.name != shop_info.shop_name:
                header_left.append(Paragraph(html.escape(loc.name), small_left_style))
            if shop_email: header_left.append(Paragraph(f"{_('Email:')} {html.escape(shop_email)}", small_left_style))
            if shop_address and (shop_info.show_company_address if shop_info else True): header_left.append(Paragraph(html.escape(shop_address), small_left_style))
            if shop_phone: header_left.append(Paragraph(f"{_('Tel:')} {html.escape(shop_phone)}", small_left_style))

            header_right = [Paragraph(doc_label, header_style)]
            meta_data_h = [
                [Paragraph(f"<b>{_('Invoice #:')}</b>", normal_style), invoice.invoice_number],
                [Paragraph(f"<b>{_('Date:')}</b>", normal_style), invoice.created_at.strftime('%d/%m/%Y')]
            ]
            if ticket:
                meta_data_h.append([Paragraph(f"<b>{_('Ticket #:')}</b>", normal_style), ticket.ticket_number])

            meta_table_h = Table(meta_data_h, colWidths=[30*mm, 40*mm])
            meta_table_h.setStyle(TableStyle([('FONTNAME', (0,0), (-1,-1), font_name), ('FONTSIZE', (0,0), (-1,-1), 9), ('ALIGN', (0,0), (-1,-1), 'LEFT')]))
            header_right.append(meta_table_h)

            header_table = Table([[header_left, header_right]], colWidths=[100*mm, 70*mm])
            header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
            elements.append(header_table)
            elements.append(Spacer(1, 5*mm))
        else:
            # Fallback for Thermal roll header
            if shop_info and shop_info.logo_path and shop_info.show_logo_on_docs:
                logo_path = os.path.join(current_app.config['LOGOS_DIR'], shop_info.logo_path)
                if os.path.exists(logo_path):
                    try:
                        img = Image(logo_path, width=25*mm, height=25*mm, kind='proportional')
                        img.hAlign = 'CENTER'
                        elements.append(img)
                        elements.append(Spacer(1, 2*mm))
                    except: pass
            elements.append(Paragraph(doc_label, header_style))
            elements.append(Paragraph(html.escape(shop_info.shop_name if (shop_info and shop_info.shop_name) else _("Repair Shop")), title_style))

        # Use physical branch details from Location instead of global shop settings for contact info
        loc = invoice.location or (ticket.location if ticket else None)
        shop_email = (loc.email if loc and loc.email else None) or (shop_info.shop_email if shop_info else None)
        shop_phone = (loc.phone if loc and loc.phone else None) or (shop_info.shop_phone if shop_info else None)
        shop_address = (loc.address if loc and loc.address else None) or (shop_info.shop_address if shop_info else None)

        if pdf_format == 'thermal':
            if loc and loc.name and shop_info and loc.name != shop_info.shop_name:
                elements.append(Paragraph(html.escape(loc.name), small_style))
            if shop_email: elements.append(Paragraph(f"{_('Email:')} {html.escape(shop_email)}", small_style))
            if shop_address and (shop_info.show_company_address if shop_info else True): elements.append(Paragraph(html.escape(shop_address), small_style))
            if shop_phone: elements.append(Paragraph(f"{_('Tel:')} {html.escape(shop_phone)}", small_style))

            if shop_info and shop_info.tax_id:
                elements.append(Paragraph(f"{_('Tax ID:')} {html.escape(shop_info.tax_id)}", small_style))
            
            elements.append(Spacer(1, 3*mm))

        # Custom formatting to strictly follow decimal settings and enable text wrapping in cells
        precision = shop_info.currency_decimals if shop_info else 2
        pattern = "#,##0" + (("." + "0" * precision) if precision > 0 else "")
        symbol = (shop_info.currency_symbol if (shop_info and shop_info.currency_symbol) else get_currency_symbol(invoice_currency, locale=locale))
        
        def local_format(amt):
            return f"{symbol} {format_decimal(amt, format=pattern, locale=locale)}"

        # Metadata table for perfect alignment on thermal rolls
        if pdf_format == 'thermal':
            meta_data = [
                [Paragraph(f"<b>{_('Ticket #:')}</b>", normal_style), ticket.ticket_number if ticket else '-'],
                [Paragraph(f"<b>{_('Invoice #:')}</b>", normal_style), invoice.invoice_number],
                [Paragraph(f"<b>{_('Date:')}</b>", normal_style), invoice.created_at.strftime('%d/%m/%Y %H:%M')],
                [Paragraph(f"<b>{_('Customer:')}</b>", normal_style), html.escape((invoice.customer.name if (invoice.customer and not invoice.customer.is_anonymized) else (ticket.customer.name if (ticket and ticket.customer and not ticket.customer.is_anonymized) else _('Walk-in'))))]
            ]
        else:
            meta_data = [[Paragraph(f"<b>{_('Customer:')}</b>", normal_style), html.escape((invoice.customer.name if (invoice.customer and not invoice.customer.is_anonymized) else (ticket.customer.name if (ticket and ticket.customer and not ticket.customer.is_anonymized) else _('Walk-in'))))]]

        active_customer = invoice.customer or (ticket.customer if ticket else None)
        if active_customer and not active_customer.is_anonymized:
            if (not shop_info or shop_info.show_customer_phone) and active_customer.phone:
                meta_data.append([Paragraph(f"<b>{_('Phone:')}</b>", normal_style), html.escape(active_customer.phone)])
            if (not shop_info or shop_info.show_customer_address) and active_customer.address:
                meta_data.append([Paragraph(f"<b>{_('Address:')}</b>", normal_style), html.escape(active_customer.address)])

        show_technician = shop_info.show_technician if shop_info else True
        show_device_sn = shop_info.show_device_sn if shop_info else True
        show_unit_prices = shop_info.show_unit_prices if shop_info else True

        if show_technician and ticket and ticket.assigned_to_user:
            meta_data.append([Paragraph(f"<b>{_('Technician:')}</b>", normal_style), html.escape(ticket.assigned_to_user.full_name or ticket.assigned_to_user.username)])

        if ticket and ticket.device:
            meta_data.append([Paragraph(f"<b>{_('Device:')}</b>", normal_style), html.escape(ticket.device.display)])
            if show_device_sn and ticket.device.serial_number:
                meta_data.append([Paragraph(f"<b>{_('S/N:')}</b>", normal_style), html.escape(ticket.device.serial_number)])

        meta_table = Table(meta_data, colWidths=meta_col_widths)
        meta_table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), font_name),
            ('FONTSIZE', (0,0), (-1,-1), 8.5),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING', (0,0), (-1,-1), 1),
            ('BOTTOMPADDING', (0,0), (-1,-1), 1),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 2*mm))
        elements.append(Paragraph("-" * (45 if pdf_format == 'thermal' else 115), normal_style))
        
        table_cell_style = ParagraphStyle('TableCell', parent=normal_style, fontSize=8, leading=10)

        if show_unit_prices:
            data = [[_('Description'), _('Qty'), _('Total')]]
            col_widths = [col_1_width, col_2_width, col_3_width]
            table_aligns = [('ALIGN', (1,0), (1,-1), 'CENTER'), ('ALIGN', (2,0), (2,-1), 'RIGHT')]
        else:
            data = [[_('Description'), _('Total')]]
            col_widths = [col_1_width + col_2_width if pdf_format == 'thermal' else 130 * mm, col_3_width]
            table_aligns = [('ALIGN', (1,0), (1,-1), 'RIGHT')]

        if ticket:
            for ts in ticket.ticket_services:
                # INTEGRITY: Use localized service names with fallback
                service_name = ts.service.name if ts.service else _('Service')
                desc = Paragraph(html.escape(_(service_name)), table_cell_style)
                if show_unit_prices:
                    data.append([desc, str(ts.quantity), local_format(ts.price_charged * ts.quantity)])
                else:
                    data.append([desc, local_format(ts.price_charged * ts.quantity)])

        for item in invoice.items:
            desc_text = html.escape(item.description)
            if (shop_info and shop_info.show_sku) and item.part and item.part.sku:
                desc_text = f"<b>[{item.part.sku}]</b> {desc_text}"

            desc = Paragraph(desc_text, table_cell_style)
            if show_unit_prices:
                data.append([desc, str(item.quantity), local_format(item.total_price)])
            else:
                data.append([desc, local_format(item.total_price)])

        table = Table(data, colWidths=col_widths)
        table_styles = [
            ('FONTNAME', (0,0), (-1,-1), font_name),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('LINEBELOW', (0,0), (-1,0), 1, brand_color),
            ('TEXTCOLOR', (0,0), (-1,0), brand_color),
        ] + table_aligns
        table.setStyle(TableStyle(table_styles))

        elements.append(table)
        if pdf_format == 'a4': elements.append(Spacer(1, 5*mm))
        elements.append(Paragraph("-" * (45 if pdf_format == 'thermal' else 115), normal_style))
        elements.append(Spacer(1, 2*mm))

        # Financial Summary Table for perfect decimal alignment
        is_paid = invoice.status == 'Paid'
        
        subtotal = invoice.subtotal_amount
        tax_amount = invoice.tax_amount
        grand_total = invoice.total_amount
        tax_rate = invoice.tax_info['rate']

        summary_data = []
        tax_lbl = getattr(shop_info, 'tax_label', 'Tax') or 'Tax'
        if tax_lbl == 'Tax':
            tax_lbl = _('Tax')

        if tax_rate > 0:
            summary_data.append([_('Subtotal:'), local_format(subtotal)])
            summary_data.append([f"{tax_lbl} ({format_decimal(tax_rate, locale=locale)}%):", local_format(tax_amount)])

        if invoice.discount_amount and invoice.discount_amount > 0:
            summary_data.append([_('Discount:'), f"- {local_format(invoice.discount_amount)}"])

        if invoice.loyalty_discount_amount and invoice.loyalty_discount_amount > 0:
            summary_data.append([
                getattr(shop_info, 'loyalty_label', _('Loyalty Discount')), 
                f"- {local_format(invoice.loyalty_discount_amount)}"
            ])

        summary_data += [
            [_('Grand Total:'), local_format(grand_total)],
            [_('Paid:'), local_format(invoice.full_payment_received)],
            [_('Balance Due:'), local_format(grand_total - invoice.full_payment_received)]
        ]

        summary_col_widths = [(col_1_width + col_2_width), col_3_width] if show_unit_prices else [col_1_width + col_2_width if pdf_format == 'thermal' else 130 * mm, col_3_width]
        summary_table = Table(summary_data, colWidths=summary_col_widths)

        # Determine where the "Grand Total" row index is
        total_row_idx = len(summary_data) - 3

        summary_table.setStyle(TableStyle([
            ('FONTNAME', (0,0), (-1,-1), font_name),
            ('FONTSIZE', (0,0), (-1,-1), 8.5),
            ('FONTNAME', (0, total_row_idx), (1, total_row_idx), f'{font_name}-Bold'),
            ('FONTSIZE', (0, total_row_idx), (1, total_row_idx), 9.5),
            ('ALIGN', (1,0), (1,-1), 'RIGHT'),
            ('LINEABOVE', (0, total_row_idx), (1, total_row_idx), 0.5, colors.black),
            ('TOPPADDING', (0,0), (-1,-1), 2),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ]))
        elements.append(summary_table)

        # Standardized Payment History
        if invoice.payments and getattr(shop_info, 'show_payment_history', True):
            elements.append(Spacer(1, 3*mm))
            elements.append(Paragraph(_('PAYMENT HISTORY:'), small_bold_style))
            for p in invoice.payments:
                p_date = p.paid_at.strftime('%d/%m/%Y')
                elements.append(Paragraph(_('%(date)s - %(method)s: %(amount)s', date=p_date, method=_(p.payment_method), amount=local_format(p.amount)), small_style))

        # Inclusion of Public Notes
        if getattr(shop_info, 'show_notes_on_docs', False):
            public_notes = [n for n in ticket.notes if not n.is_internal] if ticket else []
            if public_notes:
                elements.append(Spacer(1, 4*mm))
                elements.append(Paragraph(_('REPAIR NOTES:'), small_bold_style))
                for note in public_notes:
                    elements.append(Paragraph(f"• {html.escape(note.content)}", small_style))

        # Inclusion of Bank Details / Payment Instructions
        if getattr(shop_info, 'bank_details', None):
            elements.append(Spacer(1, 4*mm))
            elements.append(Paragraph("-" * (35 if pdf_format == 'thermal' else 100), normal_style))
            elements.append(Paragraph(_('PAYMENT INSTRUCTIONS:'), small_bold_style))
            elements.append(Paragraph(html.escape(shop_info.bank_details), small_style))

        elements.append(Spacer(1, 4*mm))

        # Customizable terms and footer
        footer_text = (shop_info.receipt_notes if is_paid else shop_info.invoice_terms) if shop_info else None
        if footer_text:
            elements.append(Paragraph("-" * (35 if pdf_format == 'thermal' else 100), normal_style))
            elements.append(Spacer(1, 2*mm))
            elements.append(Paragraph(html.escape(footer_text), small_style))
            elements.append(Spacer(1, 3*mm))
        
        if doc_type == 'invoice':
            elements.append(Spacer(1, 10*mm))
            elements.append(Paragraph("-" * (35 if pdf_format == 'thermal' else 40), normal_style))
            sig_label = shop_info.signature_label if shop_info and shop_info.signature_label else _("Customer Signature")
            elements.append(Paragraph(html.escape(sig_label), small_style))
            elements.append(Spacer(1, 5*mm))
            closing_greeting = shop_info.invoice_closing_text if shop_info else _("Thank you for your business!")
        else:
            closing_greeting = shop_info.receipt_closing_text if shop_info else _("Thank you for your business!")

        elements.append(Paragraph(html.escape(closing_greeting), small_style))
        
        doc.build(elements)
        buffer.seek(0)
        return True, buffer