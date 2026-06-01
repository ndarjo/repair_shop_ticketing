from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
import json

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

class User(UserMixin, db.Model):
    """User model for staff/technicians"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    is_superuser = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    theme_preference = db.Column(db.String(20), default='light')
    color_theme = db.Column(db.String(50), default='blue')
    currency = db.Column(db.String(10), default='USD')
    currency_decimals = db.Column(db.Integer, default=2)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    roles = db.relationship('Role', secondary=user_roles, backref=db.backref('users', lazy='dynamic'))
    permissions = db.relationship('Permission', secondary=user_permissions, backref=db.backref('users', lazy='dynamic'))
    tickets = db.relationship('Ticket', backref='assigned_to_user', lazy=True, foreign_keys='Ticket.assigned_to')
    notes = db.relationship('Note', backref='author', lazy=True)
    payments = db.relationship('Payment', backref='recorded_by_user', lazy=True)
    phase_logs = db.relationship('PhaseLog', backref='technician_user', lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def has_permission(self, permission_name):
        """Check if user has specific permission efficiently"""
        if self.is_superuser:
            return True
        
        # Check direct permissions
        direct_perm = db.session.query(Permission).join(user_permissions).filter(
            user_permissions.c.user_id == self.id,
            Permission.name == permission_name
        ).exists()

        # Check permissions inherited from roles
        role_perm = db.session.query(Permission).join(role_permissions).join(Role).join(user_roles).filter(
            user_roles.c.user_id == self.id,
            Permission.name == permission_name
        ).exists()

        # FIXED: Evaluate clauses individually to return Python booleans
        if db.session.query(direct_perm).scalar():
            return True
        return db.session.query(role_perm).scalar()
    
    def has_role(self, role_name):
        """Check if user has specific role"""
        return db.session.query(Role).join(user_roles).filter(
            user_roles.c.user_id == self.id,
            Role.name == role_name
        ).first() is not None
    
    def __repr__(self):
        return f'<User {self.username}>'


class Role(db.Model):
    """Role model for role-based access control"""
    __tablename__ = 'roles'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    permissions = db.relationship('Permission', secondary=role_permissions, backref=db.backref('roles', lazy='dynamic'))

    def __repr__(self):
        return f'<Role {self.name}>'


class Permission(db.Model):
    """Permission model for granular access control"""
    __tablename__ = 'permissions'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    def __repr__(self):
        return f'<Permission {self.name}>'


class Customer(db.Model):
    """Customer model"""
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    devices = db.relationship('Device', backref='customer', lazy=True, cascade='all, delete-orphan')
    tickets = db.relationship('Ticket', backref='customer', lazy=True)
    
    def __repr__(self):
        return f'<Customer {self.name}>'


class Device(db.Model):
    """Device model"""
    __tablename__ = 'devices'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    device_type = db.Column(db.String(100), nullable=False)
    brand = db.Column(db.String(80))
    model_number = db.Column(db.String(100))
    cpu = db.Column(db.String(100))
    ram = db.Column(db.String(50))
    storage_type = db.Column(db.String(50))
    storage_capacity = db.Column(db.String(100))
    serial_number = db.Column(db.String(100))
    color = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
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
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    items_included = db.Column(db.Text, nullable=False)
    problem_description = db.Column(db.Text, nullable=False)
    current_phase = db.Column(db.String(40), default='Open', nullable=False)
    
    device_picked_up = db.Column(db.Boolean, default=False)
    picked_up_date = db.Column(db.DateTime)
    estimated_cost = db.Column(db.Numeric(10, 2), default=0.0)
    actual_cost = db.Column(db.Numeric(10, 2), default=0.0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # FIXED: Restored truncated cascading children connections down below
    ticket_services = db.relationship('TicketService', backref='ticket', lazy=True, cascade='all, delete-orphan')
    notes = db.relationship('Note', backref='ticket', lazy=True, cascade='all, delete-orphan')
    phase_logs = db.relationship('PhaseLog', backref='ticket', lazy=True, cascade='all, delete-orphan')
    invoices = db.relationship('Invoice', backref='ticket', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='ticket', lazy=True)

    @staticmethod
    def generate_unique_number():
        """Generates a unique ticket number with collision check"""
        import uuid
        while True:
            ticket_number = f"TKT-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
            if not Ticket.query.filter_by(ticket_number=ticket_number).first():
                return ticket_number


class Service(db.Model):
    """Service model"""
    __tablename__ = 'services'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class TicketService(db.Model):
    """Bridge table mapping services attached directly to tickets"""
    __tablename__ = 'ticket_services'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    price_charged = db.Column(db.Numeric(10, 2), nullable=False)

    # Relationship to access service details from the bridge table
    service = db.relationship('Service', backref='ticket_usage', lazy=True)


class SparePart(db.Model):
    """Spare part inventory tracking model"""
    __tablename__ = 'spare_parts'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    cost = db.Column(db.Numeric(10, 2), nullable=False)
    selling_price = db.Column(db.Numeric(10, 2), nullable=False)
    stock_quantity = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class CommonProblem(db.Model):
    """Common problems helper model"""
    __tablename__ = 'common_problems'
    
    id = db.Column(db.Integer, primary_key=True)
    problem_text = db.Column(db.String(255), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Note(db.Model):
    """Internal technical tracking notes for active tickets"""
    __tablename__ = 'notes'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    note_type = db.Column(db.String(50), default='General') # e.g., 'General', 'Phase Update', 'Payment Received'
    content = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class PhaseLog(db.Model):
    """Audit log tracking ticket status lifecycle updates"""
    __tablename__ = 'phase_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    old_phase = db.Column(db.String(40))
    new_phase = db.Column(db.String(40), nullable=False)
    changed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Invoice(db.Model):
    """Invoices tied to complete tickets"""
    __tablename__ = 'invoices'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50), unique=True, nullable=False)
    
    # FIXED: Added db.ForeignKey constraint linking this column directly to the tickets table
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False)
    
    total_amount = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    status = db.Column(db.String(20), default='Unpaid') # Unpaid, Partial, Paid
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Cascade relationships remain intact
    items = db.relationship('InvoiceItem', backref='invoice', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='invoice', lazy=True)

    def calculate_total(self):
        """Recalculate total amount from items and services"""
        self.total_amount = self.subtotal + self.spare_parts_total
        return self.total_amount

    @property
    def subtotal(self):
        """Total from services attached to the ticket"""
        if not self.ticket: return 0.0
        return sum(ts.price_charged * ts.quantity for ts in self.ticket.ticket_services)

    @property
    def spare_parts_total(self):
        """Total from spare parts items on this invoice"""
        return sum(item.total_price for item in self.items)

    @property
    def down_payment(self):
        """Amount of the first payment recorded for the ticket"""
        if not self.ticket: return 0.0
        from sqlalchemy import asc
        first_payment = Payment.query.filter_by(ticket_id=self.ticket_id).order_by(asc(Payment.paid_at)).first()
        return first_payment.amount if first_payment else 0.0

    @property
    def full_payment_received(self):
        """Total payments received for this ticket"""
        if not self.ticket: return 0.0
        return sum(p.amount for p in self.ticket.payments)

    @property
    def remaining_balance(self):
        """Balance due (negative indicates change/credit)"""
        return self.total_amount - self.full_payment_received

class Payment(db.Model):
    """Financial tracking logs for invoicing transactions"""
    __tablename__ = 'payments'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(40), nullable=False) # Cash, Card, Transfer
    transaction_reference = db.Column(db.String(100))
    paid_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
class InvoiceItem(db.Model):
    __tablename__ = 'invoice_items'
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id', ondelete='CASCADE'), nullable=False)
    spare_part_id = db.Column(db.Integer, db.ForeignKey('spare_parts.id'), nullable=True)
    description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    total_price = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)