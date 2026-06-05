import sys
import os
# Bootstrap: Ensure project root is in sys.path to allow imports like 'from models import ...'
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import logging
import time
from logging.handlers import RotatingFileHandler
from flask import Flask, redirect, url_for, request, render_template, current_app, Request, jsonify, flash, session, has_request_context
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from flask_talisman import Talisman
from flask_babel import Babel, _
from flask_apscheduler import APScheduler
from babel import Locale
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_migrate import Migrate
from whitenoise import WhiteNoise
from flask_wtf.csrf import CSRFError
from cryptography.fernet import InvalidToken
from models import db, User, Role, Permission, CommonProblem, ShopSetting, Location
from setup import (
    initialize_roles_and_permissions, 
    initialize_default_data, 
    initialize_superuser,
    register_cli_commands,
    register_scheduler_tasks
)

# Global limiter instance for blueprint access
limiter = Limiter(key_func=get_remote_address, default_limits=["5000 per day", "1000 per hour"])

from config import DevelopmentConfig, ProductionConfig, TestingConfig
from datetime import datetime
import os

# Custom Request class to handle Flask 2.3+ strict JSON checks gracefully
class SilentJSONRequest(Request):
    def on_json_loading_failed(self, e):
        # Return None instead of raising 415 when a non-JSON request is probed for JSON
        return None

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
    
    # Initialize proper file logging with rotation
    if not app.testing:
        if not os.path.exists(os.path.dirname(app.config['LOG_FILE'])):
            os.makedirs(os.path.dirname(app.config['LOG_FILE']))
            
        file_handler = RotatingFileHandler(
            app.config['LOG_FILE'], 
            maxBytes=10 * 1024 * 1024, # 10MB
            backupCount=10
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(app.config['LOG_LEVEL'])
        app.logger.addHandler(file_handler)
        app.logger.setLevel(app.config['LOG_LEVEL'])
        app.logger.info('Repair Shop system starting up...')

        # Initialize external logging aggregation if URI is provided
        if app.config.get('LOG_AGGREGATION_URI'):
            from logging.handlers import HTTPHandler
            # Example: points to a log drain or central aggregator
            aggregator_handler = HTTPHandler(
                host=app.config['LOG_AGGREGATION_URI'],
                url='/log',
                method='POST'
            )
            app.logger.addHandler(aggregator_handler)

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

    # Initialize WhiteNoise for static files
    app.wsgi_app = WhiteNoise(app.wsgi_app, root=os.path.join(app.root_path, 'static'))
    app.wsgi_app.add_files(os.path.join(app.root_path, 'static', 'uploads')) # For logos etc.

    # Initialize extensions safely
    db.init_app(app)
    
    # Initialize Multi-language support (i18n)
    def get_locale():
            # Safety check for calls outside of a request context (e.g. startup seeding, CLI, scheduler)
        if not has_request_context():
            return app.config.get('BABEL_DEFAULT_LOCALE', 'en')
            
        # 1. Check user profile preference
        if current_user.is_authenticated and current_user.language_preference:
            return current_user.language_preference
        # 2. Check session (for unauthenticated users who manually switched)
        if 'language' in session:
            return session['language']
        # 3. Negotiate with browser headers
        return request.accept_languages.best_match(app.config['LANGUAGES'].keys()) or app.config.get('BABEL_DEFAULT_LOCALE', 'en')
    
    babel = Babel(app, locale_selector=get_locale)

    # Initialize Flask-Migrate
    migrate = Migrate(app, db)

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
            '\'unsafe-inline\'',
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
            'https://cdnjs.cloudflare.com',
            'data:'
        ],
        'img-src': [
            '\'self\'',
            'data:',
            'https://cdn.jsdelivr.net'
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
        
        # Optimization: Pull from current_user if authenticated to avoid redundant Admin queries
        if current_user.is_authenticated:
            symbol = currency_map.get(current_user.currency, '$')
            decimals = current_user.currency_decimals
        else:
            # Safe defaults for login/onboarding pages
            symbol = '$'
            decimals = 2
        
        # SCALABILITY: Branding is now per-location
        if current_user.is_authenticated and getattr(current_user, 'location_id', None):
            shop_info = db.session.execute(db.select(ShopSetting).filter_by(location_id=current_user.location_id)).scalar()
        else:
            # Fallback to the first available shop or global defaults
            shop_info = db.session.execute(db.select(ShopSetting)).scalar()
            
        return {
            'now': datetime.now(), 
            'current_locale': get_locale(),
            'currency_symbol': symbol, 
            'currency_decimals': decimals, 
            'shop_info': shop_info,
            'languages': app.config['LANGUAGES']
        }
    
    # Modular Blueprint Hub: Import all controllers from the routes package
    from routes import (
        main_bp, auth_bp, ticket_bp, customer_bp, 
        device_bp, admin_bp, report_bp, onboarding_bp
    )

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
            return jsonify({"error": _("Forbidden: Access Denied")}), 403

    @app.errorhandler(404)
    def not_found_error(error):
        try:
            return render_template('errors/404.html'), 404
        except:
            return jsonify({"error": _("Not Found")}), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        app.logger.error(f"Internal Server Error: {str(error)}")
        
        # Use safer checks that don't trigger JSON parsing logic
        if request.path.startswith('/api/') or request.mimetype == 'application/json':
            return jsonify({"error": "Internal server error"}), 500
            
        return render_template('errors/500.html'), 500

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        """Handle expired sessions or missing CSRF tokens gracefully"""
        app.logger.warning(f"CSRF Failure: {e.description} at {request.path}")
        flash(_("Your session has expired or the form is no longer valid. Please try again."), "info")
        return redirect(request.referrer or url_for('main.dashboard'))

    @app.errorhandler(InvalidToken)
    def handle_invalid_token(error):
        """Handle PII decryption failures gracefully"""
        app.logger.critical("PII Decryption failed! ENCRYPTION_KEY is likely mismatched with database content.")
        
        # Handle AJAX/JSON requests (search, modals)
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or '/search' in request.path:
            return jsonify({'error': _('Security Error: Unable to decrypt data. Check system configuration.')}), 500
        
        flash(_('Security Error: Unable to decrypt customer data. Your ENCRYPTION_KEY might be incorrect or has changed since this data was saved.'), 'error')
        return redirect(url_for('main.dashboard'))

    @app.errorhandler(415)
    def unsupported_media_type(error):
        # If a 415 still occurs, log it and return a clear message or redirect
        app.logger.error(f"Unsupported Media Type (415): {str(error)} at {request.path}")
        flash(_("Technical Error: Unsupported request format. Please try again."), "error")
        return render_template('Auth/login.html'), 415

    @app.before_request
    def check_onboarding():
        """Redirect superusers to onboarding if setup is incomplete"""
        if request.endpoint and \
           not any(p in request.endpoint for p in ['static', 'auth', 'onboarding']):
            if current_user.is_authenticated and current_user.is_superuser:
                settings = db.session.execute(db.select(ShopSetting)).scalar()
                if not settings or not settings.setup_completed:
                    return redirect(url_for('onboarding.setup'))
    
    # Initialize Scheduler for automated backups
    scheduler = APScheduler()
    scheduler.init_app(app)
    register_scheduler_tasks(scheduler, app)
    scheduler.start()

    # Create tables and initialize system parameters inside isolated contexts
    with app.app_context():
        db.create_all()
        initialize_roles_and_permissions()
        initialize_default_data()
        initialize_superuser()
    
    register_cli_commands(app)

    return app


if __name__ == '__main__':
    # Determine config and accessibility from environment
    env_name = os.getenv('FLASK_CONFIG', 'development')
    app = create_app(env_name)

    # Configuration is now driven by environment variables.
    # 'debug' is handled automatically by the app.config object.
    host = os.getenv('HOST', '127.0.0.1')
    port = int(os.getenv('PORT', 5000))
    app.run(host=host, port=port)
