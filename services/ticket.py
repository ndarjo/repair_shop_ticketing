from datetime import datetime
from decimal import Decimal
from typing import Tuple, Any, Optional
from flask_babel import _, get_locale
from babel.numbers import get_currency_symbol, get_currency_precision
from models import db, Ticket, PhaseLog, Note, Payment, User
from .core import FinancialService

class RepairTicketService:
    @staticmethod
    def create_ticket(customer_id: int, device_id: int, location_id: int, creator_id: int, 
                      items_included: str, problem_description: str, assigned_to: Optional[int] = None, 
                      created_at: Optional[datetime] = None, down_payment: Decimal = Decimal('0.00'), 
                      payment_method: Optional[str] = None) -> Ticket:
        """Core logic for creating a repair ticket, handling logs and down payments"""
        if created_at is None:
            created_at = datetime.now()
        
        ticket = Ticket(
            ticket_number=Ticket.generate_unique_number(),
            customer_id=customer_id,
            device_id=device_id,
            location_id=location_id,
            items_included=items_included,
            problem_description=problem_description,
            assigned_to=assigned_to,
            created_at=created_at
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
        invoice = FinancialService.get_or_create_invoice(ticket.id)
        invoice.created_at = created_at

        if down_payment > 0:
            payment = Payment(
                ticket_id=ticket.id,
                invoice_id=invoice.id,
                user_id=creator_id,
                amount=down_payment,
                payment_method=payment_method or _('Cash'),
                paid_at=created_at
            )
            db.session.add(payment)
            db.session.flush()
            
            creator = db.session.get(User, creator_id)
            user_currency = creator.currency if creator else 'USD'
            symbol = get_currency_symbol(user_currency, locale=get_locale())
            decimals = creator.currency_decimals if creator and creator.currency_decimals is not None else get_currency_precision(user_currency)
            
            payment_note = Note(
                ticket_id=ticket.id,
                user_id=creator_id,
                note_type=_('Down Payment'),
                content=_('Initial down payment of %(symbol)s%(amount)s received via %(method)s.',
                          symbol=symbol, amount=f"{down_payment:.{decimals}f}", method=payment_method or _('Cash')),
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

        # UX: Avoid redundant updates if the phase hasn't changed
        if ticket.current_phase == new_phase:
            return True, ticket

        if ticket.current_phase == 'Already Taken':
            return False, _('This ticket is locked and cannot be modified.')

        now = datetime.now()
        old_phase = ticket.current_phase
        ticket.current_phase = new_phase

        if new_phase == 'Already Taken':
            ticket.device_picked_up = True
            ticket.picked_up_date = now
            ticket.is_archived = True

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
            content = _('Phase update to %(phase)s: %(comment)s', phase=new_phase, comment=commentary)
        else:
            content = _('Ticket phase moved from %(old)s to %(new)s.', old=old_phase, new=new_phase)

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