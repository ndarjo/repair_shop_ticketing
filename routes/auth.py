from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user, login_user, logout_user
from sqlalchemy import func, select
from models import db, User
from app import limiter
from flask_babel import _

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash(_('Username and password are required'), 'error')
            return render_template('login.html')
        
        stmt = select(User).where(func.lower(User.username) == func.lower(username))
        user = db.session.scalar(stmt)
        
        if user and user.check_password(password):
            if user.is_active:
                login_user(user)
                current_app.logger.info(f"User '{user.username}' logged in successfully.")
                flash(_('Logged in successfully!'), 'success')
                return redirect(url_for('main.dashboard'))
            else:
                flash(_('Your account is deactivated. Please contact an administrator.'), 'error')
        else:
            flash(_('Invalid username or password'), 'error')
    
    return render_template('login.html')

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
            new_username = request.form.get('new_username')
            if new_username == current_user.username:
                pass # No change, avoid unnecessary error flash
            elif User.query.filter_by(username=new_username).first():
                flash(_('Username already exists'), 'error')
            else:
                current_user.username = new_username
                db.session.commit()
                flash(_('Username changed successfully!'), 'success')
        
        elif action == 'change_password':
            old_password = request.form.get('old_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            if not current_user.check_password(old_password):
                flash(_('Current password is incorrect'), 'error')
            elif new_password != confirm_password:
                flash(_('New passwords do not match'), 'error')
            elif len(new_password) < 6:
                flash(_('Password must be at least 6 characters'), 'error')
            else:
                current_user.set_password(new_password)
                db.session.commit()
                flash(_('Password changed successfully!'), 'success')
        
        elif action == 'change_theme':
            theme = request.form.get('theme')
            color = request.form.get('color_theme')
            language = request.form.get('language')
            if theme in ['light', 'dark']:
                current_user.theme_preference = theme
            if color in ['blue', 'green', 'purple', 'red', 'orange']:
                current_user.color_theme = color
            if language in current_app.config['LANGUAGES']:
                current_user.language_preference = language

            if current_user.is_superuser or current_user.has_role('manager'):
                currency = request.form.get('currency')
                if currency in ['USD', 'IDR', 'EUR', 'GBP']:
                    current_user.currency = currency

            db.session.commit()
            flash(_('Preferences updated successfully!'), 'success')
        return redirect(url_for('auth.profile'))
    return render_template('profile.html')