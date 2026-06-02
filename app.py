from flask import Flask
from flask_login import LoginManager, current_user
from models import db, User, Role, Permission, CommonProblem
from routes import auth_bp, main_bp, ticket_bp, customer_bp, admin_bp, report_bp, device_bp
from config import DevelopmentConfig
from datetime import datetime, timezone
import os

def create_app(config_name='development'):
    app = Flask(__name__)
    
    if config_name == 'development':
        app.config.from_object(DevelopmentConfig)
    
    # Initialize extensions safely
    db.init_app(app)
    
    # Initialize login manager
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    
    @login_manager.user_loader
    def load_user(user_id):
        # FIXED: Upgraded from legacy .query.get() to standard session.get()
        return db.session.get(User, int(user_id))

    @app.context_processor
    def inject_now():
        """Provides the current time to all templates for footers and headers"""
        
        # Map currency codes to symbols
        currency_map = {'USD': '$', 'IDR': 'Rp', 'EUR': '€', 'GBP': '£'}
        
        # FIXED: Deriving global shop settings from the primary Superuser/Admin account.
        # This ensures Technicians and Receptionists see the currency set by the Shop Manager.
        shop_admin = User.query.filter_by(is_superuser=True).first()
        
        symbol = currency_map.get(shop_admin.currency, '$') if shop_admin else '$'
        decimals = shop_admin.currency_decimals if shop_admin else 2
            
        return {'now': datetime.now(timezone.utc), 'currency_symbol': symbol, 'currency_decimals': decimals}
    
    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp, url_prefix='/')
    app.register_blueprint(ticket_bp, url_prefix='/ticket')
    app.register_blueprint(customer_bp, url_prefix='/customer')
    app.register_blueprint(device_bp, url_prefix='/device')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(report_bp, url_prefix='/report')
    
    # Create tables and initialize system parameters inside isolated contexts
    with app.app_context():
        db.create_all()
        # FIXED: Core roles and permissions must be built BEFORE creating users
        initialize_roles_and_permissions()
        initialize_default_data()
        initialize_superuser()
    
    return app


def initialize_superuser():
    """Create default superuser admin account if it doesn't exist"""
    # FIXED: Check if any superuser exists, rather than just checking for username 'admin'
    superuser_exists = User.query.filter_by(is_superuser=True).first()
    if not superuser_exists:
        # Fetch the system admin role to correctly assign to the superuser
        admin_role = Role.query.filter_by(name='admin').first()
        
        admin = User(
            username='admin',
            email='admin@repairshop.local',
            full_name='Administrator',
            is_superuser=True,
            is_active=True
        )
        admin.set_password('REDACTED_PASSWORD')
        
        # FIXED: Associates the built admin role with the master account if model supports it
        if admin_role and hasattr(admin, 'roles'):
            admin.roles.append(admin_role)
            
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
        ('mark_as_paid', 'Mark tickets as fully paid', 'tickets'),
        ('mark_as_taken', 'Mark devices as collected by customer', 'tickets'),
        ('archive_ticket', 'Archive completed repair tickets', 'tickets'),
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

        # Admin/Service permissions
        ('manage_services', 'Manage repair services and pricing', 'admin'),
    ]
    
    for perm_name, description, category in permissions_data:
        if not Permission.query.filter_by(name=perm_name).first():
            permission = Permission(name=perm_name, description=description, category=category)
            db.session.add(permission)
    
    db.session.commit()

    # Optional: Map default permissions to roles
    tech_role = Role.query.filter_by(name='technician').first()
    if tech_role:
        tech_perms = ['view_ticket', 'add_note', 'update_phase', 'add_service', 'view_customer', 'view_payment']
        for p_name in tech_perms:
            perm = Permission.query.filter_by(name=p_name).first()
            if perm and perm not in tech_role.permissions:
                tech_role.permissions.append(perm)
        db.session.commit()

    # Receptionist permissions
    reception_role = Role.query.filter_by(name='receptionist').first()
    if reception_role:
        reception_perms = ['create_ticket', 'create_customer', 'view_customer', 'view_ticket', 'record_payment', 'mark_as_paid']
        for p_name in reception_perms:
            perm = Permission.query.filter_by(name=p_name).first()
            if perm and perm not in reception_role.permissions:
                reception_role.permissions.append(perm)
        db.session.commit()

    # Manager permissions
    manager_role = Role.query.filter_by(name='manager').first()
    if manager_role:
        manager_perms = ['view_reports', 'manage_services', 'view_ticket', 'view_customer', 'record_payment', 'mark_as_paid', 'mark_as_taken', 'update_phase', 'archive_ticket']
        for p_name in manager_perms:
            perm = Permission.query.filter_by(name=p_name).first()
            if perm and perm not in manager_role.permissions:
                manager_role.permissions.append(perm)
        db.session.commit()


def initialize_default_data():
    """Seed the database with default common problems if empty"""
    defaults = [
        "Screen cracked/broken",
        "Battery not charging",
        "Water damage",
        "Operating system error",
        "Keyboard/Touchpad issue"
    ]
    if not CommonProblem.query.first():
        for text in defaults:
            db.session.add(CommonProblem(problem_text=text))
        db.session.commit()


if __name__ == '__main__':
    # FIXED: Handled instantiation assignment safely to global space
    app = create_app()
    app.run(debug=True, host='localhost', port=5000)
