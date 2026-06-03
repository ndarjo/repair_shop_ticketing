from flask import Flask, redirect, url_for, request, render_template, current_app, Request, jsonify, flash
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from flask_talisman import Talisman
from flask_babel import Babel, _
from flask_apscheduler import APScheduler
from babel import Locale
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from models import db, User, Role, Permission, CommonProblem, ShopSetting

# Global limiter instance for blueprint access
limiter = Limiter(key_func=get_remote_address, default_limits=["5000 per day", "1000 per hour"])

from config import DevelopmentConfig, ProductionConfig, TestingConfig
from datetime import datetime, timezone
import os
import json
from dotenv import load_dotenv, find_dotenv

# Custom Request class to handle Flask 2.3+ strict JSON checks gracefully
class SilentJSONRequest(Request):
    def on_json_loading_failed(self, e):
        # Return None instead of raising 415 when a non-JSON request is probed for JSON
        return None

# Load environment variables from env.local file if it exists
load_dotenv(find_dotenv('env.local'))
def create_app(config_name=None):
    if config_name is None:
        config_name = os.getenv('FLASK_CONFIG', 'development')
        
    app = Flask(__name__)
    app.request_class = SilentJSONRequest
    
    if config_name == 'production':
        app.config.from_object(ProductionConfig)
    elif config_name == 'testing':
        app.config.from_object(TestingConfig)
    else:
        app.config.from_object(DevelopmentConfig)
    
    # Discover available translations based on compiled .mo files
    translations_path = os.path.join(app.root_path, 'translations')
    discovered = {'en': app.config.get('SUPPORTED_LANGUAGES', {}).get('en', 'English')}
    if os.path.exists(translations_path):
        for code in os.listdir(translations_path):
            mo_file = os.path.join(translations_path, code, 'LC_MESSAGES', 'messages.mo')
            if os.path.isdir(os.path.join(translations_path, code)) and os.path.exists(mo_file):
                if code in app.config.get('SUPPORTED_LANGUAGES', {}):
                    name = app.config['SUPPORTED_LANGUAGES'][code]
                else:
                    try:
                        # Attempt to get the native name of the language (e.g. 'fr' -> 'Français')
                        name = Locale.parse(code).get_display_name(code).capitalize()
                    except Exception:
                        name = code.upper()
                discovered[code] = name
    app.config['LANGUAGES'] = discovered

    # Initialize extensions safely
    db.init_app(app)
    
    # Initialize Multi-language support (i18n)
    def get_locale():
        # Use user's preference if logged in, otherwise negotiate with browser headers
        if current_user.is_authenticated and current_user.language_preference:
            return current_user.language_preference
        return request.accept_languages.best_match(app.config['LANGUAGES'].keys()) or app.config.get('BABEL_DEFAULT_LOCALE', 'en')
    
    babel = Babel(app, locale_selector=get_locale)

    # SECURITY: Initialize CSRF protection using Flask-WTF
    csrf = CSRFProtect(app)

    # Rate Limiting
    limiter.init_app(app)

    # Support for reverse proxies (handles X-Forwarded-Proto for correct URL generation)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

    # SECURITY: Set secure HTTP headers (HSTS, No-Sniff, XSS Protection)
    # FIXED: Replaced None with a functional policy that permits authorized CDNs
    csp = {
        'default-src': '\'self\'',
        'script-src': [
            '\'self\'',
            'https://cdn.jsdelivr.net',
            'https://cdnjs.cloudflare.com'
        ],
        'style-src': [
            '\'self\'',
            'https://cdn.jsdelivr.net',
            'https://cdnjs.cloudflare.com'
        ],
        'font-src': [
            '\'self\'',
            'https://cdnjs.cloudflare.com'
        ]
    }
    Talisman(app, content_security_policy=csp, force_https=app.config.get('SESSION_COOKIE_SECURE', False))

    # Initialize login manager
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login' # type: ignore
    login_manager.login_message = _('Please log in to access this page.') # type: ignore
    
    @login_manager.user_loader
    def load_user(user_id):
        # FIXED: Upgraded from legacy .query.get() to standard session.get()
        return db.session.get(User, int(user_id))

    @app.context_processor
    def inject_now():
        """Provides the current time to all templates for footers and headers"""
        currency_map = {'USD': '$', 'IDR': 'Rp', 'EUR': '€', 'GBP': '£'}
        
        # Use safe defaults if no superuser or settings exist yet
        try:
            shop_admin = User.query.filter_by(is_superuser=True).first()
            shop_info = ShopSetting.query.first()
        except Exception:
            shop_admin = None
            shop_info = None
        
        symbol = currency_map.get(shop_admin.currency, '$') if shop_admin else '$'
        decimals = shop_admin.currency_decimals if shop_admin else 2
            
        return {
            'now': datetime.now(timezone.utc), 
            'currency_symbol': symbol, 
            'currency_decimals': decimals, 
            'shop_info': shop_info,
            'languages': app.config['LANGUAGES']
        }
    
    # Import blueprints here to avoid circular dependencies
    from routes import auth_bp, main_bp, ticket_bp, customer_bp, admin_bp, report_bp, device_bp, onboarding_bp, get_logical_backup_data

    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(main_bp, url_prefix='/')
    app.register_blueprint(ticket_bp, url_prefix='/ticket')
    app.register_blueprint(customer_bp, url_prefix='/customer')
    app.register_blueprint(device_bp, url_prefix='/device')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(report_bp, url_prefix='/report')
    app.register_blueprint(onboarding_bp, url_prefix='/onboarding')

    @app.errorhandler(403)
    def forbidden_error(error):
        try:
            return render_template('errors/403.html'), 403
        except:
            return "403 Forbidden: CSRF token missing or invalid.", 403

    @app.errorhandler(404)
    def not_found_error(error):
        try:
            return render_template('errors/404.html'), 404
        except:
            return "404 Not Found", 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        app.logger.error(f"Internal Server Error: {str(error)}")
        
        # Use safer checks that don't trigger JSON parsing logic
        if request.path.startswith('/api/') or request.mimetype == 'application/json':
            return jsonify({"error": "Internal server error"}), 500
            
        return render_template('errors/500.html'), 500

    @app.errorhandler(415)
    def unsupported_media_type(error):
        # If a 415 still occurs, log it and return a clear message or redirect
        app.logger.error(f"Unsupported Media Type (415): {str(error)} at {request.path}")
        flash(_("Technical Error: Unsupported request format. Please try again."), "error")
        return render_template('login.html'), 415

    @app.before_request
    def check_onboarding():
        """Redirect superusers to onboarding if setup is incomplete"""
        if request.endpoint and \
           not any(p in request.endpoint for p in ['static', 'auth', 'onboarding']):
            if current_user.is_authenticated and current_user.is_superuser:
                settings = ShopSetting.query.first()
                if settings and not settings.setup_completed:
                    return redirect(url_for('onboarding.setup'))
    
    # Initialize Scheduler for automated backups
    scheduler = APScheduler()
    scheduler.init_app(app)
    
    @scheduler.task('cron', id='daily_logical_backup', hour=2, minute=0)
    def scheduled_backup():
        """Automated daily logical backup task"""
        with app.app_context():
            app.logger.info("Executing scheduled system backup...")
            try:
                data = get_logical_backup_data()
                filename = f"auto_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
                backup_path = os.path.join(app.config['BACKUP_DIR'], filename)
                with open(backup_path, 'w') as f:
                    json.dump(data, f, indent=4, default=str)
                app.logger.info(f"System backup saved successfully to {backup_path}")
            except Exception as e:
                app.logger.error(f"Scheduled backup failed: {str(e)}")
    
    scheduler.start()

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
        current_app.logger.info("\n" + "="*50)
        current_app.logger.info("Superuser created successfully!")
        current_app.logger.info("Username: admin")
        current_app.logger.info("Password: REDACTED_PASSWORD")
        current_app.logger.info("="*50 + "\n")


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
        manager_perms = ['view_reports', 'manage_services', 'view_ticket', 'view_customer', 'record_payment', 'mark_as_paid', 'mark_as_taken', 'update_phase', 'archive_ticket', 'create_invoice']
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

    # Initialize shop settings
    if not ShopSetting.query.first():
        db.session.add(ShopSetting(shop_name="Repair Shop Ticketing"))

        db.session.commit()


if __name__ == '__main__':
    # Determine config and accessibility from environment
    env_name = os.getenv('FLASK_CONFIG', 'development')
    app = create_app(env_name)
    
    # Bind to 0.0.0.0 in production to allow LAN/Network access
    host = '0.0.0.0' if env_name == 'production' else 'localhost'
    debug_mode = (env_name == 'development')
    
    app.run(debug=debug_mode, host=host, port=5000)
