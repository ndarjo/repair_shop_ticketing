import io
import json
import logging
import os
import platform
import subprocess
import sys
from decimal import Decimal
from datetime import datetime
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_babel import _
from flask_login import current_user, login_required
from sqlalchemy import func, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import joinedload, selectinload
from models import (CommonProblem, Customer, Invoice, Location, Note, Payment,
                    PhaseLog, Role, Service, ShopSetting, SparePart, SparePartPriceHistory, Ticket, User, db)
from services import BackupService
from .utils import require_permission, require_superuser, safe_decimal
from werkzeug.utils import secure_filename

admin_bp = Blueprint('admin', __name__)

ALLOWED_LOGO_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}

# ==================== ADMIN ROUTES ====================

@admin_bp.route('/dashboard')
@login_required
@require_permission('admin_access_dashboard')
def dashboard():
    """Admin dashboard providing high-level system overview"""
    # INTEGRITY: Scope statistics to the specific branch for non-superusers
    if current_user.is_superuser:
        stats = {
            'users': db.session.scalar(db.select(func.count(User.id))) or 0,
            'locations': db.session.scalar(db.select(func.count(Location.id))) or 0,
            'tickets': db.session.scalar(db.select(func.count(Ticket.id))) or 0,
            'backups': len(os.listdir(current_app.config['BACKUP_DIR'])) if os.path.isdir(current_app.config['BACKUP_DIR']) else 0
        }
    else:
        loc_id = current_user.location_id
        stats = {
            'users': db.session.scalar(db.select(func.count(User.id)).where(User.location_id == loc_id)) or 0,
            'locations': 1,
            'tickets': db.session.scalar(db.select(func.count(Ticket.id)).where(Ticket.location_id == loc_id)) or 0,
            'backups': 0 # Full backups are restricted to superusers
        }
    
    return render_template('admin/dashboard.html', stats=stats)

@admin_bp.route('/users')
@login_required
@require_permission('admin_manage_users')
def manage_users():
    page = request.args.get('page', 1, type=int)
    stmt = db.select(User).options(joinedload(User.roles), joinedload(User.location))
    # INTEGRITY: Scope user management to the branch if not a superuser
    if not current_user.is_superuser:
        stmt = stmt.where(User.location_id == current_user.location_id)
    users = db.paginate(stmt, page=page, per_page=15)
    return render_template('admin/manage_users.html', users=users)

@admin_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@require_permission('admin_manage_users')
def create_user():
    # Context lookup for form options
    # SECURITY: Prevent non-superusers from granting the 'admin' role or seeing other branches
    if current_user.is_superuser:
        roles = db.session.scalars(db.select(Role)).all()
        locations = db.session.scalars(db.select(Location).order_by(Location.name)).all()
    else:
        roles = db.session.scalars(db.select(Role).where(Role.name != 'admin')).all()
        locations = [current_user.location] if current_user.location else []

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password')
        email = request.form.get('email', '').strip()
        full_name = request.form.get('full_name', '').strip()
        role_id = request.form.get('role_id', type=int)
        location_id = request.form.get('location_id', type=int)

        if not all([username, password, email, full_name, location_id is not None, role_id is not None]):
            flash(_('All fields are required.'), 'danger')
        elif len(password) < 8:
            flash(_('Password must be at least 8 characters'), 'danger')
        elif db.session.scalar(db.select(User).where(func.lower(User.username) == func.lower(username))):
            flash(_('Username already exists'), 'danger')
        elif db.session.scalar(db.select(User).where(func.lower(User.email) == func.lower(email))):
            flash(_('Email already registered with another account.'), 'danger')
        else:
            # INTEGRITY: Verify that the selected location and role exist before committing
            loc = db.session.get(Location, location_id)
            role = db.session.get(Role, role_id)
            
            # SECURITY: Enforce location and role boundaries for non-superusers during creation
            if not loc or (not current_user.is_superuser and loc.id != current_user.location_id):
                flash(_('Selected location is invalid.'), 'danger')
            elif not role:
                flash(_('Selected role is invalid.'), 'danger')
            elif not current_user.is_superuser and role.name == 'admin':
                flash(_('Security Error: You do not have permission to grant administrative roles.'), 'danger')
            else:
                new_user = User(username=username, email=email or None, full_name=full_name, location_id=loc.id)
                new_user.set_password(password)
                # Default regional settings from the branch configuration
                shop_settings = db.session.scalar(db.select(ShopSetting).filter_by(location_id=loc.id))
                if shop_settings:
                    new_user.currency = shop_settings.currency
                    new_user.currency_decimals = shop_settings.currency_decimals

                new_user.roles.append(role)
                try:
                    db.session.add(new_user)
                    db.session.commit()
                    flash(_('User created successfully'), 'success')
                    return redirect(url_for('admin.manage_users'))
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"User creation database error: {str(e)}")
                    flash(_('A database error occurred while creating the user.'), 'danger')
        
        # UX: Return form data on error to prevent data loss
        return render_template('admin/create_user.html', roles=roles, locations=locations,
                               username=username, email=email, full_name=full_name,
                               location_id=location_id, role_id=role_id)
    return render_template('admin/create_user.html', roles=roles, locations=locations)

@admin_bp.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@require_permission('admin_manage_users')
def edit_user(user_id):
    # Eager load roles and location to populate the form correctly on GET requests
    user = db.session.scalar(db.select(User).options(joinedload(User.roles), joinedload(User.location)).where(User.id == user_id))
    if not user:
        flash(_('User not found.'), 'danger')
        return redirect(url_for('admin.manage_users'))

    # SECURITY: Multi-tenancy check to prevent cross-branch user editing
    if not current_user.is_superuser and user.location_id != current_user.location_id:
        flash(_('Access denied or user not found in your branch.'), 'danger')
        return redirect(url_for('admin.manage_users'))

    # SECURITY POLICY: Administrative accounts (Superusers and Admins) can only be modified by themselves.
    # This prevents admins from demoting or changing credentials of other admins.
    is_target_admin = user.is_superuser or any(r.name == 'admin' for r in user.roles)
    if is_target_admin and user.id != current_user.id:
        flash(_('Security Policy: Administrative accounts can only be modified by their respective owners.'), 'danger')
        current_app.logger.warning(f"User {current_user.username} attempted to edit administrative account {user.username}")
        return redirect(url_for('admin.manage_users'))

    # SECURITY: Prevent non-superusers from granting the 'admin' role or moving users to other branches
    if current_user.is_superuser:
        roles = db.session.scalars(db.select(Role)).all()
        locations = db.session.scalars(db.select(Location).order_by(Location.name)).all()
    else:
        roles = db.session.scalars(db.select(Role).where(Role.name != 'admin')).all()
        locations = [current_user.location] if current_user.location else []

    if request.method == 'POST':
        is_active_requested = 'is_active' in request.form
        password = request.form.get('password')
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        loc_id = request.form.get('location_id', type=int)
        role_id = request.form.get('role_id', type=int)
        
        if not full_name or not email:
            flash(_('Full name and email are required.'), 'danger')
        elif password and len(password) < 8:
            flash(_('Password must be at least 8 characters'), 'danger')
        else:
            # SAFETY CHECK: Prevent an admin from deactivating their own account
            if user.id == current_user.id and not is_active_requested:
                flash(_('Security Warning: You cannot deactivate your own administrative account. Deactivation ignored.'), 'warning')
                is_active_requested = True

            # Integrity: Check if email is already taken by another user
            email_taken = db.session.scalar(db.select(User).where(func.lower(User.email) == func.lower(email), User.id != user_id))
            if email_taken:
                flash(_('This email address is already associated with another account.'), 'danger')
                return render_template('admin/edit_user.html', user=user, roles=roles, locations=locations,
                                       full_name=full_name, email=email, is_active=is_active_requested,
                                       location_id=loc_id, role_id=role_id)

            # Integrity: Verify location and role before assignment to prevent FK violations
            loc = db.session.get(Location, loc_id)
            role = db.session.get(Role, role_id)

            # SECURITY: Enforce location and role boundaries for non-superusers during update
            if not loc or (not current_user.is_superuser and loc.id != current_user.location_id):
                flash(_('Selected location is invalid.'), 'danger')
            elif not role:
                flash(_('Selected role is invalid.'), 'danger')
            elif not current_user.is_superuser and role.name == 'admin':
                flash(_('Security Error: You do not have permission to grant administrative roles.'), 'danger')
            # SECURITY: Prevent demoting own superuser account
            elif user.id == current_user.id and user.is_superuser and role.name != 'admin':
                flash(_('Security Error: You cannot demote your own account from the superuser role.'), 'danger')
            else:
                user.full_name = full_name
                user.email = email or None
                user.is_active = is_active_requested
                user.location_id = loc.id
                user.roles = [role] # Assign the role

                if password:
                    user.set_password(password)
                
                try:
                    db.session.commit()
                    flash(_('User updated'), 'success')
                    return redirect(url_for('admin.manage_users'))
                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"User update database error: {str(e)}")
                    flash(_('A database error occurred while updating the user.'), 'danger')
        
        # UX: Return form data on validation error to prevent data loss
        return render_template('admin/edit_user.html', user=user, roles=roles, locations=locations,
                               full_name=full_name, email=email, is_active=is_active_requested,
                               location_id=loc_id, role_id=role_id)
    
    return render_template('admin/edit_user.html', user=user, roles=roles, locations=locations)

@admin_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
@require_permission('admin_manage_users')
def delete_user(user_id):
    """Permanent removal of a staff account with safety checks"""
    if current_user.id == user_id:
        flash(_('Security Error: You cannot delete your own account.'), 'danger')
        return redirect(url_for('admin.manage_users'))

    user = db.session.get(User, user_id)
    if not user:
        flash(_('User not found.'), 'danger')
        return redirect(url_for('admin.manage_users'))

    # SECURITY: Multi-tenancy check to prevent cross-branch user deletion
    if not current_user.is_superuser and user.location_id != current_user.location_id:
        flash(_('Access denied or user not found in your branch.'), 'danger')
        return redirect(url_for('admin.manage_users'))

    # SECURITY POLICY: Administrative accounts cannot be deleted through the UI to prevent system lockout.
    # They must be handled via direct database access or CLI by a systems administrator if removal is necessary.
    is_target_admin = user.is_superuser or any(r.name == 'admin' for r in user.roles)
    if is_target_admin:
        flash(_('Security Policy: Administrative accounts cannot be deleted through the management interface.'), 'danger')
        return redirect(url_for('admin.manage_users'))

    # INTEGRITY CHECK: Prevent deletion of users with any linked history to avoid FK violations
    # This checks all tables where User is a mandatory ForeignKey
    has_tickets = db.session.scalar(db.select(func.count(Ticket.id)).where((Ticket.assigned_to == user_id) | (Ticket.creator_id == user_id)))
    has_notes = db.session.scalar(db.select(func.count(Note.id)).where(Note.user_id == user_id))
    has_payments = db.session.scalar(db.select(func.count(Payment.id)).where(Payment.user_id == user_id))
    has_logs = db.session.scalar(db.select(func.count(PhaseLog.id)).where(PhaseLog.user_id == user_id))
    has_history = db.session.scalar(db.select(func.count(SparePartPriceHistory.id)).where(SparePartPriceHistory.user_id == user_id))

    if any([has_tickets, has_notes, has_payments, has_logs, has_history]):
        flash(_('Cannot delete user: This account has linked activity (tickets, notes, or payments). Deactivate the account instead to preserve history.'), 'danger')
        return redirect(url_for('admin.manage_users'))

    try:
        db.session.delete(user)
        db.session.commit()
        flash(_('User account permanently removed.'), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"User deletion error: {str(e)}")
        flash(_('Error removing user from database.'), 'danger')
    
    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/locations', methods=['GET', 'POST'])
@login_required
@require_superuser()
def manage_locations():
    locations = db.session.scalars(db.select(Location)).all()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        address = request.form.get('address', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()

        if not name:
            flash(_('Location name is required.'), 'danger')
        elif db.session.scalar(db.select(Location).where(func.lower(Location.name) == func.lower(name))):
            flash(_('A location with this name already exists.'), 'warning')
        else:
            new_loc = Location(name=name, address=address, phone=phone, email=email or None)
            try:
                db.session.add(new_loc)
                db.session.commit()
                flash(_('New location "%(name)s" created successfully.', name=name), 'success')
                return redirect(url_for('admin.manage_locations'))
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Location creation error: {str(e)}")
                flash(_('Error saving new location.'), 'danger')
        
        # UX: Return form data on error
        return render_template('admin/locations.html', locations=locations,
                               name=name, address=address, phone=phone, email=email)

    return render_template('admin/locations.html', locations=locations)

@admin_bp.route('/locations/edit/<int:location_id>', methods=['POST'])
@login_required
@require_superuser()
def edit_location(location_id):
    """Update existing location details with optional branding synchronization"""
    loc = db.session.get(Location, location_id)
    if not loc:
        flash(_('Location not found.'), 'danger')
        return redirect(url_for('admin.manage_locations'))

    name = request.form.get('name', '').strip()
    if not name:
        flash(_('Location name is required.'), 'danger')
    else:
        # Integrity: Check for duplicate names (excluding current record)
        exists = db.session.scalar(db.select(Location).where(
            func.lower(Location.name) == func.lower(name),
            Location.id != location_id
        ))
        if exists:
            flash(_('Another location with this name already exists.'), 'warning')
            return redirect(url_for('admin.manage_locations'))
            
        loc.name = name
        loc.address = request.form.get('address', '').strip()
        loc.phone = request.form.get('phone', '').strip() or None
        loc.email = request.form.get('email', '').strip() or None
        
        try:
            db.session.commit()
            flash(_('Location "%(name)s" updated.', name=name), 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Location update error: {str(e)}")
            flash(_('Error updating location.'), 'danger')
            
    return redirect(url_for('admin.manage_locations'))

@admin_bp.route('/locations/delete/<int:location_id>', methods=['POST'])
@login_required
@require_superuser()
def delete_location(location_id):
    """Safely remove a location after verifying no entities are linked to it"""
    loc = db.session.get(Location, location_id)
    if not loc:
        flash(_('Location not found.'), 'danger')
        return redirect(url_for('admin.manage_locations'))

    # Integrity: Prevent deletion if any entities are linked to this branch
    has_users = db.session.scalar(db.select(func.count(User.id)).where(User.location_id == location_id))
    has_tickets = db.session.scalar(db.select(func.count(Ticket.id)).where(Ticket.location_id == location_id))
    has_customers = db.session.scalar(db.select(func.count(Customer.id)).where(Customer.location_id == location_id))
    has_services = db.session.scalar(db.select(func.count(Service.id)).where(Service.location_id == location_id))
    has_parts = db.session.scalar(db.select(func.count(SparePart.id)).where(SparePart.location_id == location_id))
    has_problems = db.session.scalar(db.select(func.count(CommonProblem.id)).where(CommonProblem.location_id == location_id))
    has_settings = db.session.scalar(db.select(func.count(ShopSetting.id)).where(ShopSetting.location_id == location_id))
    has_invoices = db.session.scalar(db.select(func.count(Invoice.id)).where(Invoice.location_id == location_id))
    
    if any([has_users, has_tickets, has_customers, has_services, has_parts, has_problems, has_settings, has_invoices]):
        flash(_('Cannot delete location: It is currently linked to existing records (users, tickets, customers, invoices, or shop settings).'), 'danger')
        return redirect(url_for('admin.manage_locations'))

    try:
        db.session.delete(loc)
        db.session.commit()
        flash(_('Location deleted successfully.'), 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Location deletion error: {str(e)}")
        flash(_('Error removing location from database.'), 'danger')

    return redirect(url_for('admin.manage_locations'))

@admin_bp.route('/status')
@login_required
@require_superuser()
def system_status():
    """Comprehensive diagnostic view for administrators"""
    # 1. Database Check
    db_status = _("Online")
    db_version = "Unknown"
    try:
        # Integrity: Only attempt Postgres-specific version check if using Postgres
        if 'postgresql' in current_app.config.get('SQLALCHEMY_DATABASE_URI', ''):
            db_version = db.session.scalar(text("SELECT version()"))
        else:
            db_version = _("Non-PostgreSQL Database")
    except Exception:
        db_status = _("Offline")

    # 2. Directory Permissions
    dirs_config = {
        'logs': (current_app.config['LOG_FILE'], _('Logs')),
        'backups': (current_app.config['BACKUP_DIR'], _('Backups')),
        'uploads': (current_app.config['UPLOAD_DIR'], _('Uploads'))
    }
    dir_status = {}
    for key, (path, label) in dirs_config.items():
        folder = os.path.dirname(path) if key == 'logs' else path
        exists = os.path.exists(folder)
        dir_status[label] = {
            'path': os.path.basename(folder) or folder,
            'exists': exists,
            'writable': os.access(folder, os.W_OK) if exists else False
        }

    # 3. System Info
    sys_info = {
        _('Operating System'): f"{platform.system()} {platform.release()}",
        _('Python Version'): sys.version.split()[0],
        _('Environment'): os.getenv('FLASK_CONFIG', 'development'),
        _('System Timezone'): datetime.now().astimezone().tzname()
    }

    # 4. Config Summary (Masked)
    config_summary = {
        _('Log Level'): logging.getLevelName(current_app.config['LOG_LEVEL']),
        _('Backup Schedule'): _('%(time)s UTC', time=f"{current_app.config['BACKUP_HOUR']:02d}:{current_app.config['BACKUP_MINUTE']:02d}"),
        _('Session Lifetime'): _('%(hours)d hours', hours=int(current_app.config['PERMANENT_SESSION_LIFETIME'].total_seconds() / 3600))
    }

    return render_template('admin/system_status.html', 
                           db_status=db_status, 
                           db_version=db_version,
                           dir_status=dir_status,
                           sys_info=sys_info,
                           config_summary=config_summary)

@admin_bp.route('/backup', methods=['GET', 'POST'])
@login_required
@require_superuser()
def backup():
    if request.method == 'POST':
        backup_type = request.form.get('backup_type')
        if backup_type == 'json_data':
            try:
                data = BackupService.get_system_logical_data()
                filename = f"manual_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                path = os.path.join(current_app.config['BACKUP_DIR'], filename)
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                flash(_('Logical backup created successfully: %(name)s', name=filename), 'success')
            except Exception as e:
                current_app.logger.error(f"JSON Backup generation failed: {str(e)}")
                flash(_('Error: Failed to generate logical backup file.'), 'danger')
                
        elif backup_type == 'full_db':
            filename = f"full_dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dump"
            path = os.path.join(current_app.config['BACKUP_DIR'], filename)
            
            try:
                db_url = current_app.config.get('SQLALCHEMY_DATABASE_URI', '')
                
                if 'postgresql' in db_url:
                    url_obj = make_url(db_url)
                    env = os.environ.copy()
                    if url_obj.password:
                        env['PGPASSWORD'] = url_obj.password
                    
                    cmd = ['pg_dump', '-Fc', '-f', path]
                    if url_obj.host: cmd.extend(['-h', url_obj.host])
                    if url_obj.port: cmd.extend(['-p', str(url_obj.port)])
                    if url_obj.username: cmd.extend(['-U', url_obj.username])
                    cmd.append(url_obj.database)
                    
                    subprocess.run(cmd, env=env, check=True, capture_output=True)
                    flash(_('Full database snapshot created successfully: %(name)s', name=filename), 'success')
                else:
                    flash(_('Full snapshots are only supported for PostgreSQL installations.'), 'warning')
            except subprocess.CalledProcessError as e:
                err_msg = e.stderr.decode() if e.stderr else _("Process returned non-zero exit status.")
                flash(_('Error: pg_dump failed. %(msg)s', msg=err_msg), 'danger')
            except FileNotFoundError:
                flash(_('Error: pg_dump utility not found. Please ensure PostgreSQL client tools are installed.'), 'danger')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Backup failed: {str(e)}")
                flash(_('An unexpected error occurred during the backup process.'), 'danger')

        return redirect(url_for('admin.backup'))

    backup_dir = current_app.config['BACKUP_DIR']
    backups = sorted(os.listdir(backup_dir), reverse=True) if os.path.isdir(backup_dir) else []
    return render_template('admin/backup.html', backups=backups)

@admin_bp.route('/backup/download/<filename>')
@login_required
@require_superuser()
def download_backup_file(filename):
    """Download a backup file from the server's repository"""
    filename = secure_filename(filename)
    path = os.path.join(current_app.config['BACKUP_DIR'], filename)
    if os.path.isfile(path):
        return send_file(path, as_attachment=True)
    flash(_('File not found.'), 'danger')
    return redirect(url_for('admin.backup'))

@admin_bp.route('/backup/restore', methods=['POST'])
@login_required
@require_superuser()
def restore():
    if 'backup_file' not in request.files:
        flash(_('No file uploaded.'), 'danger')
        return redirect(url_for('admin.backup'))
    
    file = request.files['backup_file']
    if file.filename == '':
        flash(_('No file selected.'), 'danger')
        return redirect(url_for('admin.backup'))

    if file and file.filename.endswith('.dump'):
        filename = secure_filename(file.filename)
        temp_path = os.path.join(current_app.config['BACKUP_DIR'], f"restore_{int(datetime.now().timestamp())}_{filename}")
        file.save(temp_path)
        
        try:
            success, message = BackupService.restore_full_backup(temp_path)
            if success:
                flash(_('Database restored successfully. System state has been reverted.'), 'success')
            else:
                flash(message, 'danger')
        finally:
            if os.path.exists(temp_path): os.remove(temp_path)
    else:
        flash(_('Only .dump files (PostgreSQL binary) are supported for automated restore.'), 'warning')

    return redirect(url_for('admin.backup'))

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@require_permission('admin_manage_branding')
def settings():
    # INTEGRITY: Robust lookup for multi-tenancy. 
    # Fetch specific branch settings first, then check for global settings, or fallback to any record.
    loc_id = current_user.location_id
    
    # Fetch settings specific to this branch
    branch_settings = db.session.scalar(db.select(ShopSetting).filter_by(location_id=loc_id))
    
    # For template rendering defaults, fall back to global settings
    shop_settings = branch_settings
    if not shop_settings and loc_id is not None:
        shop_settings = db.session.scalar(db.select(ShopSetting).filter_by(location_id=None))
    if not shop_settings:
        shop_settings = db.session.scalar(db.select(ShopSetting).limit(1))
    
    if request.method == 'POST':
        shop_name = request.form.get('shop_name', '').strip()
        shop_address = request.form.get('shop_address', '').strip()
        shop_phone = request.form.get('shop_phone', '').strip()
        tax_id = request.form.get('tax_id', '').strip()
        shop_email = request.form.get('shop_email', '').strip()
        invoice_terms = request.form.get('invoice_terms', '').strip()
        receipt_notes = request.form.get('receipt_notes', '').strip()
        currency = request.form.get('currency')
        currency_symbol = request.form.get('currency_symbol', '$').strip()
        invoice_label = request.form.get('invoice_label', '').strip() or _('INVOICE')
        receipt_label = request.form.get('receipt_label', '').strip() or _('RECEIPT')
        signature_label = request.form.get('signature_label', '').strip() or _('Customer Signature')
        invoice_closing_text = request.form.get('invoice_closing_text', '').strip() or _('Thank you for your business!')
        receipt_closing_text = request.form.get('receipt_closing_text', '').strip() or _('Thank you for your business!')
        decimals = request.form.get('currency_decimals', type=int)
        show_technician = 'show_technician' in request.form
        show_device_sn = 'show_device_sn' in request.form
        show_unit_prices = 'show_unit_prices' in request.form
        show_customer_phone = 'show_customer_phone' in request.form
        show_customer_address = 'show_customer_address' in request.form
        show_sku = 'show_sku' in request.form
        enable_loyalty_points = 'enable_loyalty_points' in request.form
        enable_discounts = 'enable_discounts' in request.form
        loyalty_label = request.form.get('loyalty_label', '').strip() or _('Loyalty Points')
        loyalty_points_per_currency = safe_decimal(request.form.get('loyalty_points_per_currency') or '1.00')
        loyalty_point_value = safe_decimal(request.form.get('loyalty_point_value') or '0.01')
        brand_color = request.form.get('brand_color', '#0d6efd').strip()
        show_wholesale_cost = 'show_wholesale_cost' in request.form
        pdf_page_format = request.form.get('pdf_page_format', 'thermal')
        show_logo_on_docs = 'show_logo_on_docs' in request.form
        show_payment_history = 'show_payment_history' in request.form
        bank_details = request.form.get('bank_details', '').strip()
        show_notes_on_docs = 'show_notes_on_docs' in request.form
        tax_label = request.form.get('tax_label', '').strip() or _('Tax')
        show_company_address = 'show_company_address' in request.form
        tax_rate = safe_decimal(request.form.get('tax_rate', '0'))

        if not shop_name:
            flash(_('Shop name is required.'), 'danger')
        else:
            # INTEGRITY: Ensure we operate on branch-specific settings. 
            # If they don't exist yet, create them instead of modifying the global fallback.
            if not branch_settings:
                target_loc_id = loc_id or (shop_settings.location_id if shop_settings else db.session.scalar(db.select(Location.id).limit(1)))
                shop_settings = ShopSetting(location_id=target_loc_id)
                db.session.add(shop_settings)
            else:
                shop_settings = branch_settings

            shop_settings.shop_name = shop_name
            shop_settings.shop_address = shop_address
            shop_settings.shop_phone = shop_phone
            shop_settings.shop_email = shop_email
            shop_settings.invoice_terms = invoice_terms
            shop_settings.receipt_notes = receipt_notes
            shop_settings.invoice_label = invoice_label
            shop_settings.tax_id = tax_id
            shop_settings.signature_label = signature_label
            shop_settings.receipt_label = receipt_label
            # Save new closing greetings
            shop_settings.invoice_closing_text = invoice_closing_text
            shop_settings.receipt_closing_text = receipt_closing_text
            if currency: shop_settings.currency = currency
            shop_settings.currency_symbol = currency_symbol
            if decimals is not None: shop_settings.currency_decimals = decimals
            shop_settings.show_technician = show_technician
            shop_settings.show_device_sn = show_device_sn
            shop_settings.show_unit_prices = show_unit_prices
            shop_settings.show_customer_phone = show_customer_phone
            shop_settings.show_customer_address = show_customer_address
            shop_settings.show_sku = show_sku
            shop_settings.enable_loyalty_points = enable_loyalty_points
            shop_settings.enable_discounts = enable_discounts
            shop_settings.loyalty_label = loyalty_label
            shop_settings.loyalty_points_per_currency = loyalty_points_per_currency
            shop_settings.loyalty_point_value = loyalty_point_value
            shop_settings.show_wholesale_cost = show_wholesale_cost
            shop_settings.brand_color = brand_color
            shop_settings.pdf_page_format = pdf_page_format
            shop_settings.show_logo_on_docs = show_logo_on_docs
            shop_settings.show_payment_history = show_payment_history
            shop_settings.tax_rate = tax_rate
            shop_settings.bank_details = bank_details
            shop_settings.show_notes_on_docs = show_notes_on_docs
            shop_settings.tax_label = tax_label
            shop_settings.show_company_address = show_company_address

            # Handle Logo Upload
            file = request.files.get('shop_logo')
            if file and file.filename and '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in ALLOWED_LOGO_EXTENSIONS:
                filename = secure_filename(f"logo_loc_{shop_settings.location_id or 0}_{file.filename}")
                logo_dir = current_app.config['LOGOS_DIR']
                new_path = os.path.join(logo_dir, filename)
                file.save(new_path)

                if shop_settings.logo_path and shop_settings.logo_path != filename:
                    old_path = os.path.join(logo_dir, shop_settings.logo_path)
                    if os.path.exists(old_path): os.remove(old_path)
                shop_settings.logo_path = filename

            try:
                db.session.commit()
                flash(_('Settings updated successfully!'), 'success')
                return redirect(url_for('admin.settings'))
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Settings update error: {str(e)}")
                flash(_('Failed to save settings.'), 'danger')

        # UX Integrity: Return form data on error to prevent data loss
        return render_template('admin/settings.html', settings=shop_settings,
                               shop_name=shop_name, shop_address=shop_address,
                               shop_phone=shop_phone, shop_email=shop_email,
                               selected_currency=currency, selected_currency_decimals=decimals,
                               tax_rate=tax_rate, tax_label=tax_label, tax_id=tax_id, loyalty_label=loyalty_label,
                               loyalty_points_per_currency=loyalty_points_per_currency, loyalty_point_value=loyalty_point_value,
                               brand_color=brand_color,
                               invoice_terms=invoice_terms, receipt_notes=receipt_notes,
                               invoice_label=invoice_label, receipt_label=receipt_label,
                               signature_label=signature_label,
                               show_wholesale_cost=show_wholesale_cost, # Pass to template
                               invoice_closing_text=invoice_closing_text,
                               receipt_closing_text=receipt_closing_text, 
                               pdf_page_format=pdf_page_format,
                               show_technician=show_technician, show_device_sn=show_device_sn,
                               show_unit_prices=show_unit_prices, show_customer_phone=show_customer_phone,
                               show_customer_address=show_customer_address, show_sku=show_sku,
                               enable_loyalty_points=enable_loyalty_points, enable_discounts=enable_discounts,
                               show_logo_on_docs=show_logo_on_docs, show_payment_history=show_payment_history,
                               show_notes_on_docs=show_notes_on_docs, show_company_address=show_company_address,
                               bank_details=bank_details)

    return render_template('admin/settings.html', settings=shop_settings,
                           tax_rate=shop_settings.tax_rate if shop_settings else Decimal('0.00'),
                           tax_label=shop_settings.tax_label if shop_settings else _('Tax'),
                           bank_details=shop_settings.bank_details if shop_settings else '')

@admin_bp.route('/backup/export')
@login_required
@require_superuser()
def export_backup():
    """Manual trigger for system backup data"""
    data = BackupService.get_system_logical_data()
    # UX Integrity: Return as a downloadable file instead of a browser JSON dump
    output = json.dumps(data, indent=4).encode('utf-8')
    return send_file(
        io.BytesIO(output),
        mimetype='application/json',
        as_attachment=True,
        download_name=f"system_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )