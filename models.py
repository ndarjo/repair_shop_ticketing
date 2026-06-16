from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
from sqlalchemy import or_
from decimal import Decimal
from cryptography.fernet import Fernet
import re
import hashlib
import hmac
from flask import current_app

db = SQLAlchemy()

# FIXED: Moved association tables to the top so User relationship mapping compiles smoothly
user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True)
)

user_permissions = db.Table('user_permissions',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
)

role_permissions = db.Table('role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
)

class Location(db.Model):
    """Represents a physical shop location/branch"""
    __tablename__ = 'locations'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    address = db.Column(db.Text)
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    
    # Relationships for logical multi-tenancy and data isolation
    users = db.relationship('User', backref='location', lazy=True, cascade='all, delete-orphan')
    customers = db.relationship('Customer', backref='location', lazy=True, cascade='all, delete-orphan')
    tickets = db.relationship('Ticket', backref='location', lazy=True, cascade='all, delete-orphan')
    services = db.relationship('Service', backref='location', lazy=True, cascade='all, delete-orphan')
    spare_parts = db.relationship('SparePart', backref='location', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Location {self.name}>'

class User(UserMixin, db.Model):
    """User model for staff/technicians"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    is_superuser = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    theme_preference = db.Column(db.String(20), nullable=False, default='light')
    color_theme = db.Column(db.String(50), nullable=False, default='blue')
    language_preference = db.Column(db.String(5), nullable=False, default='en')
    currency = db.Column(db.String(10), nullable=False, default='USD')
    currency_decimals = db.Column(db.Integer, nullable=False, default=2)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    
    # Multi-tenancy: Link user to a specific branch
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True, index=True)

    # Relationships
    roles = db.relationship('Role', secondary=user_roles, backref=db.backref('users', lazy='dynamic'))
    permissions = db.relationship('Permission', secondary=user_permissions, backref=db.backref('users', lazy='dynamic'))
    created_tickets = db.relationship('Ticket', back_populates='creator', lazy=True, foreign_keys='Ticket.creator_id')
    tickets = db.relationship('Ticket', back_populates='assigned_to_user', lazy=True, foreign_keys='Ticket.assigned_to')
    notes = db.relationship('Note', backref='author', lazy=True)
    payments = db.relationship('Payment', backref='recorded_by_user', lazy=True)
    phase_logs = db.relationship('PhaseLog', backref='technician_user', lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def has_permission(self, permission_name):
        """Check if user has specific permission efficiently"""
        if not self.is_active:
            return False
        if self.is_superuser:
            return True
        
        # Optimized check: Existence query for the specific permission name
        # covering both direct user-permission links and role-based inheritance.
        stmt = db.select(Permission.id).where(
            Permission.name == permission_name,
            or_(
                Permission.users.any(id=self.id),
                Permission.roles.any(Role.users.any(id=self.id))
            )
        )
        return db.session.scalar(stmt) is not None
    
    def has_role(self, role_name):
        """Check if user has specific role using modern select"""
        if not self.is_active:
            return False
        stmt = db.select(Role).join(user_roles).where(
            user_roles.c.user_id == self.id,
            Role.name == role_name
        )
        return db.session.scalar(stmt) is not None
    
    def __repr__(self):
        return f'<User {self.username}>'


class Role(db.Model):
    """Role model for role-based access control"""
    __tablename__ = 'roles'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    permissions = db.relationship('Permission', secondary=role_permissions, backref=db.backref('roles', lazy='dynamic'))

    def __repr__(self):
        return f'<Role {self.name}>'


class Permission(db.Model):
    """Permission model for granular access control"""
    __tablename__ = 'permissions'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50), nullable=False, default='General', index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    def __repr__(self):
        return f'<Permission {self.name}>'


class Customer(db.Model):
    """Customer model"""
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # GDPR: Encryption at Rest. Name is kept plaintext for searchability, 
    # while Phone and Address are encrypted using AES-256.
    name = db.Column(db.String(120), nullable=False, index=True)
    _phone_encrypted = db.Column('phone', db.Text, nullable=False)

    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True, index=True)

    _address_encrypted = db.Column('address', db.Text, nullable=True)
    
    # GDPR Blind Index: A hash of the phone number used for exact searches 
    # without revealing the actual number to the database engine.
    phone_hash = db.Column(db.String(64), index=True)
    is_anonymized = db.Column(db.Boolean, nullable=False, server_default='false', default=False, index=True)

    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    devices = db.relationship('Device', backref='customer', lazy=True, cascade='all, delete-orphan')
    tickets = db.relationship('Ticket', backref='customer', lazy=True)

    def _get_cipher(self):
        """Internal helper to get the Fernet cipher"""
        return Fernet(current_app.config['ENCRYPTION_KEY'].encode())

    @staticmethod
    def get_search_hash(value):
        """Generates a SHA-256 blind index for searching encrypted data"""
        if not value:
            return None
        # INTEGRITY: Normalize search value by removing non-alphanumeric characters for phone indexing
        normalized = re.sub(r'\D', '', str(value))
        if not normalized:
            return None
        salt = current_app.config.get('BLIND_INDEX_SALT', current_app.config['SECRET_KEY'])
        return hmac.new(salt.encode(), normalized.encode(), hashlib.sha256).hexdigest()

    @property
    def phone(self):
        if not self._phone_encrypted: return ""
        return self._get_cipher().decrypt(self._phone_encrypted.encode()).decode()

    @phone.setter
    def phone(self, value):
        if value:
            # Consistency: Store hash of normalized digits to allow formatted search queries
            normalized = re.sub(r'\D', '', value)
            self._phone_encrypted = self._get_cipher().encrypt(value.encode()).decode()
            self.phone_hash = self.get_search_hash(normalized)
        else:
            self._phone_encrypted = ""
            self.phone_hash = None

    @property
    def address(self):
        if not self._address_encrypted: return ""
        return self._get_cipher().decrypt(self._address_encrypted.encode()).decode()

    @address.setter
    def address(self, value):
        if value:
            self._address_encrypted = self._get_cipher().encrypt(value.encode()).decode()
        else:
            self._address_encrypted = ""

    def anonymize(self):
        """GDPR Compliance: Right to be Forgotten. Scrub PII but keep logs."""
        self.name = f"DELETED_USER_{self.id}"
        self.phone = "0000000000"
        self.address = "ANONYMIZED"
        self.is_anonymized = True

    def export_data(self):
        """GDPR Compliance: Right to Data Portability."""
        return {
            'customer_info': {'name': self.name, 'phone': self.phone, 'address': self.address},
            'devices': [{'type': d.device_type, 'brand': d.brand, 'sn': d.serial_number} for d in self.devices],
            'tickets': [{'id': t.ticket_number, 'phase': t.current_phase} for t in self.tickets]
        }
    
    def __repr__(self):
        return f'<Customer {self.name}>'


class Device(db.Model):
    """Device model"""
    __tablename__ = 'devices'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False, index=True)
    device_type = db.Column(db.String(100), nullable=False)
    brand = db.Column(db.String(80))
    model_number = db.Column(db.String(100))
    cpu = db.Column(db.String(100))
    ram = db.Column(db.String(50))
    storage_type = db.Column(db.String(50))
    storage_capacity = db.Column(db.String(100))
    serial_number = db.Column(db.String(100), index=True)
    color = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    tickets = db.relationship('Ticket', backref='device', lazy=True, cascade='all, delete-orphan')
    
    @property
    def display(self):
        """Standardized display name for the device"""
        return f"{self.brand or ''} {self.model_number or ''} ({self.device_type})".strip()

    def __repr__(self):
        return f'<Device {self.brand} {self.model_number}>'


class Ticket(db.Model):
    """Repair ticket model"""
    __tablename__ = 'tickets'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(20), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id', ondelete='CASCADE'), nullable=False, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id', ondelete='CASCADE'), nullable=False, index=True)
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    
    creator = db.relationship('User', back_populates='created_tickets', foreign_keys=[creator_id])
    assigned_to_user = db.relationship('User', back_populates='tickets', foreign_keys=[assigned_to])

    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=False, index=True)

    items_included = db.Column(db.Text, nullable=False)
    problem_description = db.Column(db.Text, nullable=False)
    current_phase = db.Column(db.String(40), default='Open', nullable=False, index=True)
    
    is_archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
    device_picked_up = db.Column(db.Boolean, nullable=False, default=False)
    picked_up_date = db.Column(db.DateTime)
    estimated_cost = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal('0.00'))
    actual_cost = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal('0.00'))
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    
    # Relationships
    ticket_services = db.relationship('TicketService', backref='ticket', lazy=True, cascade='all, delete-orphan')
    notes = db.relationship('Note', backref='ticket', lazy=True, cascade='all, delete-orphan')
    phase_logs = db.relationship('PhaseLog', backref='ticket', lazy=True, cascade='all, delete-orphan')
    invoices = db.relationship('Invoice', backref='ticket', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='ticket', lazy=True, cascade='all, delete-orphan')

    __table_args__ = (
        # Optimization for dashboard queries filtering active/archived phases
        db.Index('idx_ticket_phase_archived', 'current_phase', 'is_archived'),
    )

    @staticmethod
    def generate_unique_number():
        """Generates a unique ticket number with collision check"""
        while True:
            ticket_number = f"TKT-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
            stmt = db.select(Ticket.id).filter_by(ticket_number=ticket_number)
            if not db.session.scalar(stmt):
                return ticket_number

    @property
    def services_total(self):
        """Calculates the total value of all services on this ticket"""
        return sum((ts.price_charged * ts.quantity for ts in self.ticket_services), Decimal('0.00'))

    @property
    def parts_total(self):
        """Calculates the total value of all parts across all associated invoices"""
        return sum((item.total_price for inv in self.invoices for item in inv.items), Decimal('0.00'))

    @property
    def grand_total(self):
        """Sum of services and parts"""
        return self.services_total + self.parts_total

    @property
    def total_paid(self):
        """Sum of all payments recorded for this ticket"""
        return sum((p.amount for p in self.payments), Decimal('0.00'))

    @property
    def balance_due(self):
        """Remaining amount to be paid"""
        return self.grand_total - self.total_paid

    @property
    def timeline(self):
        """Combined chronological list of phase changes and notes for the Audit UI"""
        events = []
        for log in self.phase_logs:
            events.append({
                'type': 'phase',
                'timestamp': log.changed_at,
                'user': log.technician_user.full_name if log.technician_user else 'System',
                'old_phase': log.old_phase,
                'new_phase': log.new_phase
            })
        for note in self.notes:
            events.append({
                'type': 'note',
                'timestamp': note.created_at,
                'user': note.author.full_name if note.author else 'System',
                'content': note.content,
                'note_type': note.note_type,
                'is_internal': note.is_internal
            })
        return sorted(events, key=lambda x: x['timestamp'], reverse=True)

    @property
    def down_payment(self):
        """Amount of the first payment recorded for the ticket. Required for system integrity with BackupService."""
        stmt = db.select(Payment).where(Payment.ticket_id == self.id).order_by(Payment.paid_at.asc()).limit(1)
        first_payment = db.session.scalar(stmt)
        return first_payment.amount if first_payment else Decimal('0.00')

    @property
    def payment_method(self):
        """Payment method of the first payment. Required for system integrity with BackupService."""
        stmt = db.select(Payment).where(Payment.ticket_id == self.id).order_by(Payment.paid_at.asc()).limit(1)
        first_payment = db.session.scalar(stmt)
        return first_payment.payment_method if first_payment else None

    def __repr__(self):
        return f'<Ticket {self.ticket_number}>'


class Service(db.Model):
    """Service model"""
    __tablename__ = 'services'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal('0.00'))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    __table_args__ = (db.UniqueConstraint('name', 'location_id', name='_service_location_uc'),)

    def __repr__(self):
        return f'<Service {self.name}>'


class TicketService(db.Model):
    """Bridge table mapping services attached directly to tickets"""
    __tablename__ = 'ticket_services'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id', ondelete='CASCADE'), nullable=False, index=True)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    price_charged = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal('0.00'))

    # Relationship to access service details from the bridge table
    service = db.relationship('Service', backref='ticket_usage', lazy=True)

    def __repr__(self):
        return f'<TicketService T:{self.ticket_id} S:{self.service_id}>'


class SparePart(db.Model):
    """Spare part inventory tracking model"""
    __tablename__ = 'spare_parts'
    
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(100), index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    cost = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal('0.00'))
    selling_price = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal('0.00'))
    stock_quantity = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        db.UniqueConstraint('name', 'location_id', name='_part_location_uc'),
        db.UniqueConstraint('sku', 'location_id', name='_part_sku_location_uc'),
    )

    def __repr__(self):
        return f'<SparePart {self.sku or self.name}>'

class SparePartPriceHistory(db.Model):
    """Tracks historical price and cost movements for inventory items"""
    __tablename__ = 'spare_part_price_history'
    
    id = db.Column(db.Integer, primary_key=True)
    spare_part_id = db.Column(db.Integer, db.ForeignKey('spare_parts.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    old_cost = db.Column(db.Numeric(10, 2))
    new_cost = db.Column(db.Numeric(10, 2), nullable=False)
    old_price = db.Column(db.Numeric(10, 2))
    new_price = db.Column(db.Numeric(10, 2), nullable=False)
    changed_at = db.Column(db.DateTime, default=datetime.now, index=True)

    # Relationship back to the part
    spare_part = db.relationship('SparePart', backref=db.backref('price_history', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User', lazy=True)


class CommonProblem(db.Model):
    """Common problems helper model"""
    __tablename__ = 'common_problems'
    
    id = db.Column(db.Integer, primary_key=True)
    problem_text = db.Column(db.String(255), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    __table_args__ = (db.UniqueConstraint('problem_text', 'location_id', name='_problem_location_uc'),)

    def __repr__(self):
        return f'<CommonProblem {self.problem_text[:20]}...>'


class Note(db.Model):
    """Internal technical tracking notes for active tickets"""
    __tablename__ = 'notes'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    note_type = db.Column(db.String(50), default='General') # e.g., 'General', 'Phase Update', 'Payment Received'
    content = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    def __repr__(self):
        return f'<Note {self.id} on Ticket {self.ticket_id}>'


class PhaseLog(db.Model):
    """Audit log tracking ticket status lifecycle updates"""
    __tablename__ = 'phase_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    old_phase = db.Column(db.String(40))
    new_phase = db.Column(db.String(40), nullable=False)
    changed_at = db.Column(db.DateTime, default=datetime.now, index=True)

    def __repr__(self):
        return f'<PhaseLog {self.id}: {self.old_phase} -> {self.new_phase}>'


class Invoice(db.Model):
    """Invoices tied to complete tickets"""
    __tablename__ = 'invoices'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    
    # Link to the associated ticket
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=True, index=True)
    
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id', ondelete='CASCADE'), nullable=True, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id', ondelete='CASCADE'), nullable=True, index=True)

    customer = db.relationship('Customer', backref='invoices')
    
    total_amount = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal('0.00'))
    status = db.Column(db.String(20), default='Unpaid', index=True) # Unpaid, Partial, Paid
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    
    # Cascade relationships remain intact
    items = db.relationship('InvoiceItem', backref='invoice', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='invoice', lazy=True, cascade='all, delete-orphan')

    def calculate_total(self):
        """Recalculate total amount from items and services"""
        self.total_amount = self.subtotal + self.spare_parts_total
        return self.total_amount

    @property
    def subtotal(self):
        """Total from services attached to the ticket"""
        return self.ticket.services_total if self.ticket else Decimal('0.00')

    @property
    def spare_parts_total(self):
        """Total from all items (parts and POS items) on this invoice"""
        return sum((item.total_price for item in self.items), Decimal('0.00'))

    @property
    def down_payment(self):
        """Amount of the first payment recorded for the ticket"""
        if not self.ticket_id: return Decimal('0.00')
        stmt = db.select(Payment).where(Payment.ticket_id == self.ticket_id).order_by(Payment.paid_at.asc()).limit(1)
        first_payment = db.session.scalar(stmt)
        return first_payment.amount if first_payment else Decimal('0.00')

    @property
    def full_payment_received(self):
        """Total payments received for this invoice"""
        return sum((p.amount for p in self.payments), Decimal('0.00'))

    @property
    def remaining_balance(self):
        """Balance due (negative indicates change/credit)"""
        return self.total_amount - self.full_payment_received

    def __repr__(self):
        return f'<Invoice {self.invoice_number}>'

class Payment(db.Model):
    """Financial tracking logs for invoicing transactions"""
    __tablename__ = 'payments'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id', ondelete='CASCADE'), nullable=True, index=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal('0.00'))
    payment_method = db.Column(db.String(40), nullable=False) # Cash, Card, Transfer
    transaction_reference = db.Column(db.String(100))
    paid_at = db.Column(db.DateTime, default=datetime.now, index=True)

    def __repr__(self):
        return f'<Payment {self.id}: {self.amount}>'

class InvoiceItem(db.Model):
    __tablename__ = 'invoice_items'
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id', ondelete='CASCADE'), nullable=False, index=True)
    spare_part_id = db.Column(db.Integer, db.ForeignKey('spare_parts.id', ondelete='SET NULL'), nullable=True, index=True)
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    cost_price = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal('0.00'))
    unit_price = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal('0.00'))
    total_price = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal('0.00'))

    # Relationship for easier inventory access
    part = db.relationship('SparePart', backref='invoice_line_items', lazy=True)

    def __repr__(self):
        return f'<InvoiceItem {self.description[:20]}>'

class ShopSetting(db.Model):
    """Global shop configuration for invoices and branding"""
    __tablename__ = 'shop_settings'
    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True, index=True)
    shop_name = db.Column(db.String(120), default='Repair Shop')
    shop_address = db.Column(db.Text)
    shop_phone = db.Column(db.String(30))
    shop_email = db.Column(db.String(120))
    logo_path = db.Column(db.String(255))
    currency = db.Column(db.String(10), nullable=False, default='USD')
    currency_decimals = db.Column(db.Integer, nullable=False, default=2)
    setup_completed = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self):
        return f'<ShopSetting {self.shop_name}>'