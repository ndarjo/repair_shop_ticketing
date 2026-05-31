from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    """User model for technicians/staff"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='technician')  # admin, technician, manager
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    tickets = db.relationship('Ticket', backref='assigned_to_user', lazy=True, foreign_keys='Ticket.assigned_to')
    notes = db.relationship('Note', backref='author', lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'


class Customer(db.Model):
    """Customer model"""
    __tablename__ = 'customers'
    
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True)
    phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.Text)
    city = db.Column(db.String(80))
    zip_code = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    tickets = db.relationship('Ticket', backref='customer', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Customer {self.first_name} {self.last_name}>'
    
    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'


class Ticket(db.Model):
    """Repair ticket model"""
    __tablename__ = 'tickets'
    
    STATUS_CHOICES = [
        'Open',
        'In Progress',
        'Waiting for Parts',
        'On Hold',
        'Completed',
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
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    device_type = db.Column(db.String(100), nullable=False)  # Phone, Laptop, etc.
    device_brand = db.Column(db.String(80))
    device_model = db.Column(db.String(80))
    serial_number = db.Column(db.String(100))
    
    issue_description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='Open', nullable=False)
    priority = db.Column(db.String(10), default='Medium', nullable=False)
    
    estimated_cost = db.Column(db.Float)
    actual_cost = db.Column(db.Float)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    
    # Relationships
    notes = db.relationship('Note', backref='ticket', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Ticket {self.ticket_number}>'


class Note(db.Model):
    """Notes/updates on tickets"""
    __tablename__ = 'notes'
    
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Note on Ticket {self.ticket_id}>'


class Service(db.Model):
    """Service catalog"""
    __tablename__ = 'services'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    base_price = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Service {self.name}>'