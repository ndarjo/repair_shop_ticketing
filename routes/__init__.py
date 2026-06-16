from .admin import admin_bp
from .auth import auth_bp
from .customer import customer_bp
from .device import device_bp
from .inventory import inventory_bp
from .main import main_bp
from .pos import pos_bp
from .report import report_bp
from .setup import onboarding_bp
from .services import services_bp
from .ticket import ticket_bp

__all__ = [
    'admin_bp',
    'auth_bp',
    'customer_bp',
    'device_bp',
    'inventory_bp',
    'main_bp',
    'onboarding_bp',
    'pos_bp',
    'report_bp',
    'services_bp',
    'ticket_bp'
]