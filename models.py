from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """User model for staff/technicians"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    is_superuser = db.Column(db.Boolean, default=False)  # Super admin flag
    is_active = db.Column(db.Boolean, default=True)
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
    name = db.Column(db.String(50), unique=True, nullable=False)  # admin, technician, receptionist, manager
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
    category = db.Column(db.String(50))  # tickets, customers, users, payments, reports
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Permission {self.name}>'


# Association table for user roles
user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id')),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'))
)

# Association table for user permissions
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
    address = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    devices = db.relationship('Device', backref='customer', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Customer {self.name}>'


class Device(db.Model):
    """Device model - each customer can have multiple devices with detailed specifications"""
    __tablename__ = 'devices'
    
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    device_type = db.Column(db.String(100), nullable=False)  # Phone, Laptop, Tablet, Desktop, etc.
    brand = db.Column(db.String(80))
    model = db.Column(db.String(80))
    model_number = db.Column(db.String(100))
    cpu = db.Column(db.String(100))  # Processor information
    ram = db.Column(db.String(50))  # RAM specification (e.g., 8GB, 16GB)
    storage_type = db.Column(db.String(50))  # HDD, SSD, or both
    storage_capacity = db.Column(db.String(100))  # Storage capacity with unit (e.g., 256GB, 512GB SSD + 1TB HDD)
    serial_number = db.Column(db.String(100))
    color = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    tickets = db.relationship('Ticket', backref='device', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Device {self.brand} {self.model}>'


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
    
    PRIORITY_CHOICES = [
        'Low',
        'Medium',
        'High',
        'Urgent'
    ]
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(20), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Inclusions and problems
    items_included = db.Column(db.Text, nullable=False)  # What customer brought with device (charger, cables, etc.)
    problem_description = db.Column(db.Text, nullable=False)  # What problem device has
    
    # Phase tracking
    current_phase = db.Column(db.String(20), default='Open', nullable=False)  # Current phase
    priority = db.Column(db.String(10), default='Medium', nullable=False)
    
    device_picked_up = db.Column(db.Boolean, default=False)  # Track if device was picked up
    picked_up_date = db.Column(db.DateTime)  # When device was picked up
    
    estimated_cost = db.Column(db.Float)
    actual_cost = db.Column(db.Float)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # When ticket was created
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime)  # When repair was finished
    
    # Relationships
    notes = db.relationship('Note', backref='ticket', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', backref='ticket', lazy=True, cascade='all, delete-orphan')
    phase_logs = db.relationship('PhaseLog', backref='ticket', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Ticket {self.ticket_number}>'
    
    @property
    def customer(self):
        return Customer.query.get(self.customer_id)


class PhaseLog(db.Model):
    """Log for tracking phase changes and their details"""
    __tablename__ = 'phase_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Technician who made the change
    phase = db.Column(db.String(50), nullable=False)  # Phase name
    commentary = db.Column(db.Text)  # What was done in this phase
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)  # When this phase was logged
    
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
    note_type = db.Column(db.String(50), default='General')  # Type of note
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
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # Who recorded the payment
    amount = db.Column(db.Float, nullable=False)
    payment_type = db.Column(db.String(20), nullable=False)  # Down Payment, Full Payment
    payment_method = db.Column(db.String(50))  # Cash, Card, Check, Online
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Payment {self.payment_type} for Ticket {self.ticket_id}>'