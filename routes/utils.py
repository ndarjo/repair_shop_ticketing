from functools import wraps
from flask import request, jsonify, flash, redirect, url_for, current_app
from flask_login import current_user
from flask_babel import _
from decimal import Decimal
import decimal

def safe_decimal(value, default='0.00'):
    """Helper to convert string to Decimal without crashing on invalid input"""
    try:
        if isinstance(value, Decimal):
            return value
        if value is None or str(value).strip() == '':
            return Decimal(default)
        return Decimal(str(value).replace(',', ''))
    except (ValueError, TypeError, decimal.InvalidOperation):
        return Decimal(default)

def require_permission(permission_name):
    """Decorator to check if user has specific permission"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': _('Authentication required')}), 401
                flash(_('Please log in first.'), 'error')
                return redirect(url_for('auth.login', next=request.full_path))
            if not current_user.has_permission(permission_name):
                current_app.logger.warning(f"Access denied for user {current_user.username} to permission {permission_name}")
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': _('Permission denied')}), 403
                flash(_('You do not have permission to access this page.'), 'error')
                return redirect(url_for('main.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_superuser():
    """Decorator to check if user is superuser"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': _('Authentication required')}), 401
                flash(_('Please log in first.'), 'error')
                return redirect(url_for('auth.login', next=request.full_path))
            if not current_user.is_superuser:
                current_app.logger.warning(f"Access denied for non-superuser {current_user.username}")
                if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'error': _('Permission denied')}), 403
                flash(_('You do not have permission to access this page.'), 'error')
                return redirect(url_for('main.dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator