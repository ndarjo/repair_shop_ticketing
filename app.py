from flask import Flask
from flask_login import LoginManager
from models import db, User, Role, Permission
from routes import auth_bp, main_bp, ticket_bp, customer_bp, admin_bp, report_bp, device_bp
from config import DevelopmentConfig
import os

def create_app(config_name='development'):
    app = Flask(__name__)
    
    if config_name == 'development':
        app.config.from_object(DevelopmentConfig)
    
    # Initialize extensions
    db.init_app(app)
    
    # Initialize login manager
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp, url_prefix='/')
    app.register_blueprint(ticket_bp, url_prefix='/ticket')
    app.register_blueprint(customer_bp, url_prefix='/customer')
    app.register_blueprint(device_bp, url_prefix='/device')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(report_bp, url_prefix='/report')
    
    # Create tables and initialize superuser
    with app.app_context():
        db.create_all()
        initialize_superuser()
        initialize_roles_and_permissions()
    
    return app


def initialize_superuser():
    """Create default superuser admin account if it doesn't exist"""
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin',
            email='admin@repairshop.local',
            full_name='Administrator',
            is_superuser=True,
            is_active=True
        )
        admin.set_password('REDACTED_PASSWORD')
        db.session.add(admin)
        db.session.commit()
        print("\n" + "="*50)
        print("Superuser created successfully!")
        print("Username: admin")
        print("Password: REDACTED_PASSWORD")
        print("="*50 + "\n")


def initialize_roles_and_permissions():
    """Initialize default roles and permissions"""
    
    # Define roles
    roles_data = [
        ('admin', 'System Administrator'),
        ('technician', 'Repair Technician'),
        ('receptionist', 'Receptionist/Customer Service'),
        ('manager', 'Store Manager'),
    ]
    
    for role_name, description in roles_data:
        if not Role.query.filter_by(name=role_name).first():
            role = Role(name=role_name, description=description)
            db.session.add(role)
    
    db.session.commit()
    
    # Define permissions grouped by category
    permissions_data = [
        # Ticket permissions
        ('create_ticket', 'Create new repair tickets', 'tickets'),
        ('view_ticket', 'View ticket details', 'tickets'),
        ('edit_ticket', 'Edit ticket information', 'tickets'),
        ('delete_ticket', 'Delete tickets', 'tickets'),
        ('add_note', 'Add notes to tickets', 'tickets'),
        ('update_phase', 'Update ticket phase', 'tickets'),
        ('add_service', 'Add services to tickets', 'tickets'),
        ('create_invoice', 'Create invoices', 'tickets'),
        
        # Customer permissions
        ('create_customer', 'Create new customers', 'customers'),
        ('view_customer', 'View customer details', 'customers'),
        ('edit_customer', 'Edit customer information', 'customers'),
        ('delete_customer', 'Delete customers', 'customers'),
        ('create_device', 'Add devices to customers', 'customers'),
        ('edit_device', 'Edit device information', 'customers'),
        ('delete_device', 'Delete devices', 'customers'),
        
        # Payment permissions
        ('record_payment', 'Record payments', 'payments'),
        ('view_payment', 'View payment history', 'payments'),
        ('delete_payment', 'Delete payment records', 'payments'),
        
        # User management permissions
        ('create_user', 'Create new user accounts', 'users'),
        ('view_user', 'View user details', 'users'),
        ('edit_user', 'Edit user information', 'users'),
        ('delete_user', 'Delete user accounts', 'users'),
        ('manage_permissions', 'Manage user permissions and roles', 'users'),
        
        # Report permissions
        ('view_reports', 'View reports and analytics', 'reports'),
        ('export_data', 'Export data', 'reports'),
    ]
    
    for perm_name, description, category in permissions_data:
        if not Permission.query.filter_by(name=perm_name).first():
            permission = Permission(name=perm_name, description=description, category=category)
            db.session.add(permission)
    
    db.session.commit()


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='localhost', port=5000)
