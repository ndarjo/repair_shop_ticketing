from datetime import datetime
from decimal import Decimal
from typing import Tuple, Any, Optional
from flask_babel import _, get_locale
from babel.numbers import format_currency
from sqlalchemy import or_
from models import db, Ticket, PhaseLog, Note, Payment, User, Customer, Device, Role, ShopSetting, Invoice
from .core import FinancialService

class RepairTicketService:
    @staticmethod
    def get_assignable_technicians(location_id: int):
        """Fetches active technicians eligible for assignment at a specific location"""
        # INTEGRITY: Use 'any' to check role membership to avoid potential duplicate rows from joins
        stmt = db.select(User).where(
            User.is_active == True,
            User.roles.any(Role.name == 'technician'),
            or_(User.location_id == location_id, User.is_superuser == True)
        ).order_by(User.full_name)
        return db.session.scalars(stmt).all()

    @staticmethod
    def create_ticket(customer_id: int, device_id: int, location_id: int, creator_id: int, 
                      items_included: str, problem_description: str, assigned_to: Optional[int] = None, 
                      created_at: Optional[datetime] = None, down_payment: Decimal = Decimal('0.00'), 
                      payment_method: Optional[str] = None, include_tax: bool = True) -> Ticket:
        """Core logic for creating a repair ticket, handling logs and down payments"""
        
        # SECURITY & INTEGRITY: Authorization and Multi-tenancy check
        creator = db.session.get(User, creator_id)
        if not creator or not creator.is_active:
            raise ValueError(_('Authorized user required'))
        
        if not creator.is_superuser:
            if location_id != creator.location_id:
                raise ValueError(_('Access denied'))
            if not creator.has_permission('create_ticket'):
                raise ValueError(_('Permission denied'))

        # Data Integrity: Cross-model location validation
        customer = db.session.get(Customer, customer_id)
        if not customer or customer.location_id != location_id:
            raise ValueError(_('Invalid customer for this location'))
        
        device = db.session.get(Device, device_id)
        if not device or device.customer_id != customer_id:
            raise ValueError(_('Invalid device for this customer'))

        # Integrity: Validate assigned technician if provided
        if assigned_to:
            technician = db.session.get(User, assigned_to)
            if not technician or not technician.is_active:
                raise ValueError(_('Assigned technician not found or inactive'))
            if not technician.is_superuser and technician.location_id != location_id:
                raise ValueError(_('Technician belongs to a different location'))
            # INTEGRITY: Ensure the assigned user has the correct role
            if not technician.is_superuser and not technician.has_role('technician'):
                raise ValueError(_('Assigned user must be a technician'))

        if created_at is None:
            created_at = datetime.now()
        
        # Data Integrity: Normalize and validate required fields
        problem_description = problem_description.strip() if problem_description else ""
        if not problem_description:
            raise ValueError(_('Problem description is required'))

        ticket = Ticket(
            ticket_number=Ticket.generate_unique_number(),
            customer_id=customer_id,
            device_id=device_id,
            location_id=location_id,
            items_included=items_included.strip() if items_included else None,
            problem_description=problem_description,
            assigned_to=assigned_to,
            current_phase='Open',
            created_at=created_at,
            include_tax=include_tax
        )
        db.session.add(ticket)
        db.session.flush() 
        
        initial_log = PhaseLog(
            ticket_id=ticket.id,
            user_id=creator_id,
            old_phase=None,
            new_phase='Open',
            changed_at=created_at
        )
        db.session.add(initial_log)

        # Ensure invoice exists for intake tracking and matches ticket creation date
        invoice = FinancialService.get_or_create_invoice(ticket.id, customer_id=customer_id, location_id=location_id)
        invoice.created_at = created_at
        db.session.flush()

        if down_payment < 0:
            raise ValueError(_('Down payment cannot be negative'))

        if down_payment > 0:
            # SECURITY: Recording a down payment requires payment processing permission
            if not creator.is_superuser and not creator.has_permission('process_payments'):
                raise ValueError(_('Permission denied to record payments'))

            # INTEGRITY: Store the payment method key in the database, translate only for display or notes
            payment_method_key = payment_method.strip() if (payment_method and payment_method.strip()) else 'Cash'
            payment = Payment(
                ticket_id=ticket.id, # Ensure ticket_id is passed for consistency
                invoice_id=invoice.id,
                user_id=creator_id,
                amount=down_payment,
                payment_method=payment_method_key,
                paid_at=created_at
            )
            db.session.add(payment)
            db.session.flush()
            
            # INTEGRITY: Automated notes should reflect the branch currency settings.
            # Robust lookup: Try specific branch settings first, fallback to global settings.
            shop_info = db.session.scalar(db.select(ShopSetting).filter_by(location_id=location_id)) or \
                        db.session.scalar(db.select(ShopSetting).filter_by(location_id=None))
            if not shop_info:
                shop_info = db.session.scalar(db.select(ShopSetting).limit(1))

            user_currency = shop_info.currency if shop_info and shop_info.currency else (creator.currency or 'USD')
            
            payment_note = Note(
                ticket_id=ticket.id,
                user_id=creator_id,
                note_type=_('Down Payment'),
                content=_('Initial down payment of %(amount)s received via %(method)s.',
                          amount=format_currency(down_payment, user_currency, locale=get_locale()),
                          method=_(payment_method_key)),
                is_internal=True,
                created_at=created_at
            )
            db.session.add(payment_note)
            
        FinancialService.sync_invoice_status(invoice.id) # Ensure invoice status is synced regardless of down payment

        return ticket

    @staticmethod
    def update_phase(ticket_id: int, new_phase: str, user_id: int, commentary: Optional[str] = None) -> Tuple[bool, Any]:
        """Handles ticket lifecycle updates, audit logging, and automated notes"""
        ticket = db.session.get(Ticket, ticket_id)
        if not ticket:
            return False, _('Ticket not found')

        # SECURITY: Permission and Multi-tenancy check
        user = db.session.get(User, user_id)
        if not user or not user.is_active:
            return False, _('Authorized user required')
        
        # SECURITY: Enforce multi-tenancy and granular phase update permissions
        if not user.is_superuser:
            if ticket.location_id != user.location_id:
                return False, _('Access denied')
            if not user.has_permission('update_phase'):
                return False, _('Permission denied')

        # SECURITY: Enforce granular permission for terminal lifecycle events
        if new_phase == 'Already Taken' and not user.is_superuser:
            if not user.has_permission('mark_as_taken'):
                return False, _('Permission denied to mark ticket as taken')

        # UX: Avoid redundant updates if the phase hasn't changed
        if ticket.current_phase == new_phase:
            return True, ticket

        # UX/Integrity: Locked status logic. Only superusers can revert an archived ticket to fix mistakes.
        if ticket.current_phase == 'Already Taken' and not user.is_superuser:
            return False, _('This ticket is locked and cannot be modified.')

        now = datetime.now()
        old_phase = ticket.current_phase
        ticket.current_phase = new_phase

        if new_phase == 'Already Taken':
            ticket.device_picked_up = True
            ticket.picked_up_date = now
            ticket.is_archived = False # Keep in history view until manually archived
            # Integrity: Perform a final recalculation to lock in the current VAT/prices 
            # before the ticket is effectively frozen.
            invoice = db.session.scalar(db.select(Invoice).where(Invoice.ticket_id == ticket.id))
            if invoice:
                invoice.calculate_total()
                FinancialService.sync_invoice_status(invoice.id)
        elif old_phase == 'Already Taken' and new_phase != 'Already Taken':
            # UX Fix: Revert pickup status if an admin moves the ticket out of archived state
            ticket.device_picked_up = False
            ticket.picked_up_date = None

        log = PhaseLog(
            ticket_id=ticket.id,
            user_id=user_id,
            old_phase=old_phase,
            new_phase=new_phase,
            changed_at=now
        )
        db.session.add(log)

        note_type = _('Phase Update')
        if commentary:
            content = _('Phase update to %(phase)s: %(comment)s', phase=_(new_phase), comment=commentary)
        else:
            content = _('Ticket phase moved from %(old)s to %(new)s.', old=_(old_phase), new=_(new_phase))

        note = Note(
            ticket_id=ticket.id,
            user_id=user_id,
            note_type=note_type,
            content=content,
            is_internal=True,
            created_at=now
        )
        db.session.add(note)

        return True, ticket