from urllib.parse import urlparse

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_babel import _
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func, select
from babel.numbers import list_currencies

from app import limiter
from models import User, db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
        
    if request.method == 'POST':
        # UX: Strip whitespace to prevent login failures due to trailing spaces
        username = request.form.get('username', '').strip()
        password = request.form.get('password')

        if not username or not password:
            flash(_('Username and password are required'), 'danger')
            return render_template('Auth/login.html', last_username=username)
        
        stmt = select(User).where(func.lower(User.username) == func.lower(username))
        user = db.session.scalar(stmt)
        
        if user and user.check_password(password):
            if user.is_active:
                login_user(user)
                current_app.logger.info(f"User '{user.username}' logged in successfully.")
                flash(_('Logged in successfully!'), 'success')
                
                # UX Integrity: Redirect to the page the user was originally trying to access
                next_page = request.args.get('next')
                if not next_page or urlparse(next_page).netloc != '' or not next_page.startswith('/'):
                    next_page = url_for('main.dashboard')
                return redirect(next_page)
            else:
                flash(_('Your account is deactivated. Please contact an administrator.'), 'danger')
                return render_template('Auth/login.html', last_username=username)
        else:
            flash(_('Invalid username or password'), 'danger')
            return render_template('Auth/login.html', last_username=username)
    
    return render_template('Auth/login.html')

@auth_bp.route('/set_language/<code>')
def set_language(code):
    """Endpoint for unauthenticated users to switch display language"""
    if code in current_app.config['LANGUAGES']:
        session['language'] = code
        if current_user.is_authenticated:
            current_user.language_preference = code
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Language preference update failed: {str(e)}")
                flash(_('Failed to save language preference to your profile.'), 'danger')
            
    ref = request.referrer
    if ref:
        parsed_ref = urlparse(ref)
        parsed_url = urlparse(request.url)
        if parsed_ref.netloc == parsed_url.netloc or not parsed_ref.netloc:
            return redirect(ref)
    return redirect(url_for('main.dashboard'))

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash(_('You have been logged out.'), 'success')
    return redirect(url_for('auth.login'))

@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'change_username':
            new_username = request.form.get('new_username', '').strip()
            if not new_username:
                flash(_('Username is required'), 'danger')
            elif new_username == current_user.username:
                pass # No change, avoid unnecessary error flash
            elif db.session.scalar(select(User).where(func.lower(User.username) == func.lower(new_username), User.id != current_user.id)):
                flash(_('Username already exists'), 'danger')
            else:
                try:
                    current_user.username = new_username
                    db.session.commit()
                    flash(_('Username changed successfully!'), 'success')
                    return redirect(url_for('auth.profile'))
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Username update database error: {str(e)}")
                    flash(_('A database error occurred while updating your username.'), 'danger')
        
        elif action == 'change_password':
            old_password = request.form.get('old_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            if not old_password or not current_user.check_password(old_password):
                flash(_('Current password is incorrect'), 'danger')
            elif new_password != confirm_password:
                flash(_('New passwords do not match'), 'danger')
            # Security Integrity: Enforce a more modern minimum password length
            elif not new_password or len(new_password) < 8:
                flash(_('Password must be at least 8 characters'), 'danger')
            else:
                try:
                    current_user.set_password(new_password)
                    db.session.commit()
                    flash(_('Password changed successfully!'), 'success')
                    return redirect(url_for('auth.profile'))
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Password update database error: {str(e)}")
                    flash(_('A database error occurred while updating your password.'), 'danger')
        
        elif action == 'change_theme':
            theme = request.form.get('theme')
            color = request.form.get('color_theme')
            language = request.form.get('language')
            # Added 'system' support for modern OS theme detection
            if theme in ['light', 'dark', 'system']:
                current_user.theme_preference = theme
            if color in ['blue', 'green', 'purple', 'red', 'orange']:
                current_user.color_theme = color
            if language in current_app.config['LANGUAGES']:
                current_user.language_preference = language
                session['language'] = language # UX Sync: Update current session language immediately

            if current_user.has_permission('view_reports'):
                currency = request.form.get('currency')
                if currency in list_currencies():
                    current_user.currency = currency
                
                decimals = request.form.get('currency_decimals', type=int)
                if decimals in [0, 2, 3]:
                    current_user.currency_decimals = decimals

            try:
                db.session.commit()
                flash(_('Preferences updated successfully!'), 'success')
                return redirect(url_for('auth.profile'))
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Preferences update database error: {str(e)}")
                flash(_('A database error occurred while saving your preferences.'), 'danger')
                
    # UX Integrity: Default to current username on GET or failures
    display_username = (request.form.get('new_username') or current_user.username or '').strip()
    return render_template('Auth/profile.html', new_username=display_username)