from .admin import admin_bp
from .auth import auth_bp
from .main import main_bp
from .report import report_bp
from .ticket import ticket_bp
from .device import device_bp
from .customer import customer_bp
from .setup import onboarding_bp

__all__ = ['admin_bp', 'auth_bp', 'main_bp', 'report_bp', 'ticket_bp', 'device_bp', 'customer_bp', 'onboarding_bp']