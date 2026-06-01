from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import json

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """User model for staff/technicians"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), nullable=True)  # Optional
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    is_superuser = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    theme_preference = db.Column(db.String(20), default='light')  # light or dark
    color_theme = db.Column(db.String(50), default='blue')  # blue, green, purple, red, orange
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    role = db.relationship('Role', secondary='user_roles', backref=db.backref('users', lazy='dynamic'))
    permissions = db.relationship('Permission', secondary='user_permissions', backref=db.backref('users', lazy='dynamic'))
    tickets = db.relationship('Ticket', backref='assigned_to_user', lazy=True, foreign_keys='Ticket.assigned_to')
    notes = db.relationship('Note', backref='author', lazy=True)
    payments = db.relationship('Payment', backref='recorded_by_user', lazy=True)
    phase_logs = db.relationship('PhaseLog', backref='technician_user', lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def has_permission(self, permission_name):
        """Check if user has specific permission"""
        if self.is_superuser:
            return True
        return Permission.query.filter_by(name=permission_name).filter(Permission.users.contains(self)).first() is not None
    
    def has_role(self, role_name):
        """Check if user has specific role"""
        return Role.query.filter_by(name=role_name).filter(Role.users.contains(self)).first() is not None
    
    def __repr__(self):
        return f'<User {self.username}>'


class Role(db.Model):
    """Role model for role-based access control"""
    __tablename__ = 'roles'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Role {self.name}>'


class Permission(db.Model):
    """Permission model for granular access control"""
    __tablename__ = 'permissions'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Permission {self.name}>'


# Association tables
user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id')),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'))
)

user_permissions = db.Table('user_permissions',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id')),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id'))
)


class Customer(db.Model):
    """Customer model - simplified with only name, phone, and address"""
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.Text, nullable=True)  # Optional
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    devices = db.relationship('Device', backref='customer', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Customer {self.name}>'


class Device(db.Model):
    """Device model - each customer can have multiple devices"""
    __tablename__ = 'devices'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    device_type = db.Column(db.String(100), nullable=False)
    brand = db.Column(db.String(80))
    model = db.Column(db.String(80))
    model_number = db.Column(db.String(100))
    cpu = db.Column(db.String(100))
    ram = db.Column(db.String(50))
    storage_type = db.Column(db.String(50))
    storage_capacity = db.Column(db.String(100))
    serial_number = db.Column(db.String(100))
    color = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    tickets = db.relationship('Ticket', backref='device', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Device {self.brand} {self.model}>'


class Service(db.Model):
    """Service model - repair services that can be added to tickets"""
    __tablename__ = 'services'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    ticket_services = db.relationship('TicketService', backref='service', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Service {self.name}>'


class SparePart(db.Model):
    """Spare part/hardware model - parts used in repairs"""
    __tablename__ = 'spare_parts'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    cost = db.Column(db.Float, nullable=False)  # Cost to shop
    selling_price = db.Column(db.Float, nullable=False)  # Price charged to customer
    stock_quantity = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    invoice_items = db.relationship('InvoiceItem', backref='spare_part', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<SparePart {self.name}>'


class CommonProblem(db.Model):
    """Common problems for quick selection when creating tickets"""
    __tablename__ = 'common_problems'
    
    id = db.Column(db.Integer, primary_key=True)
    problem_text = db.Column(db.String(255), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<CommonProblem {self.problem_text}>'


class Ticket(db.Model):
    """Repair ticket model"""
    __tablename__ = 'tickets'
    
    PHASE_CHOICES = [
        'Open',
        'Diagnostic',
        'Waiting for Parts',
        'Repairing',
        'Finished',
        'Cancelled'
    ]
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(20), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    items_included = db.Column(db.Text, nullable=False)
    problem_description = db.Column(db.Text, nullable=False)
    
    current_phase = db.Column(db.String(20), default='Open', nullable=False)
    
    device_picked_up = db.Column(db.Boolean, default=False)
    picked_up_date = db.Column(db.DateTime)
    
    estimated_cost = db.Column(db.Float)
    actual_cost = db.Column(db.Float)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    
    # Relationships
    notes = db.relationship('Note', backref='ticket', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='ticket', lazy=True, cascade='all, delete-orphan')
    phase_logs = db.relationship('PhaseLog', backref='ticket', lazy=True, cascade='all, delete-orphan')
    ticket_services = db.relationship('TicketService', backref='ticket', lazy=True, cascade='all, delete-orphan')
    invoice = db.relationship('Invoice', backref='ticket', uselist=False, lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Ticket {self.ticket_number}>'
    
    @property
    def customer(self):
        return Customer.query.get(self.customer_id)


class TicketService(db.Model):
    """Services added to a ticket"""
    __tablename__ = 'ticket_services'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    price = db.Column(db.Float, nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<TicketService {self.service_id} for Ticket {self.ticket_id}>'


class Invoice(db.Model):
    """Invoice model - generated after repair completion"""
    __tablename__ = 'invoices'
    
    INVOICE_STATUSES = ['Draft', 'Issued', 'Partially Paid', 'Paid', 'Cancelled']
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(20), unique=True, nullable=False)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    
    subtotal = db.Column(db.Float, default=0)  # Services subtotal
    spare_parts_total = db.Column(db.Float, default=0)  # Spare parts total
    total_amount = db.Column(db.Float, default=0)  # Grand total
    
    down_payment = db.Column(db.Float, default=0)  # Down payment already received
    full_payment_received = db.Column(db.Float, default=0)  # Full payment received
    remaining_balance = db.Column(db.Float, default=0)  # Amount still owed
    
    status = db.Column(db.String(20), default='Draft')
    issued_date = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime)
    paid_date = db.Column(db.DateTime)
    
    # Relationships
    items = db.relationship('InvoiceItem', backref='invoice', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Invoice {self.invoice_number}>'


class InvoiceItem(db.Model):
    """Items in an invoice (spare parts/hardware)"""
    __tablename__ = 'invoice_items'
    
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    spare_part_id = db.Column(db.Integer, db.ForeignKey('spare_parts.id'), nullable=False)
    
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Float, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<InvoiceItem {self.spare_part_id} in Invoice {self.invoice_id}>'


class PhaseLog(db.Model):
    """Log for tracking phase changes"""
    __tablename__ = 'phase_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    phase = db.Column(db.String(50), nullable=False)
    commentary = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<PhaseLog Ticket {self.ticket_id} - {self.phase}>'


class Note(db.Model):
    """Notes/updates on tickets"""
    __tablename__ = 'notes'
    
    NOTE_TYPES = [
        'General',
        'Down Payment',
        'Full Payment',
        'Device Picked Up',
        'Technical Update',
        'Customer Communication'
    ]
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    note_type = db.Column(db.String(50), default='General')
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Note on Ticket {self.ticket_id}>'


class Payment(db.Model):
    """Payment tracking for tickets"""
    __tablename__ = 'payments'
    
    PAYMENT_TYPES = [
        'Down Payment',
        'Full Payment',
        'Additional Payment'
    ]
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_type = db.Column(db.String(20), nullable=False)
    payment_method = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Payment {self.payment_type} for Ticket {self.ticket_id}>'


class Backup(db.Model):
    """Database backup for local restoration"""
    __tablename__ = 'backups'
    
    id = db.Column(db.Integer, primary_key=True)
    backup_name = db.Column(db.String(120), nullable=False)
    backup_data = db.Column(db.Text, nullable=False)  # JSON formatted backup
    file_size = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    def __repr__(self):
        return f'<Backup {self.backup_name}>'
