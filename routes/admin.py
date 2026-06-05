import os
import json
import subprocess
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, send_file
from flask_login import login_required, current_user
from models import db, User, Role, Location, ShopSetting, Permission, CommonProblem, Service, SparePart
from services import BackupService
from sqlalchemy.orm import joinedload
from .utils import require_permission, require_superuser, safe_decimal
from flask_babel import _
from werkzeug.utils import secure_filename

admin_bp = Blueprint('admin', __name__)

# ==================== ADMIN ROUTES ====================

@admin_bp.route('/dashboard')
@login_required
@require_superuser()
def dashboard():
    return render_template('admin/dashboard.html')

@admin_bp.route('/users')
@login_required
@require_superuser()
def manage_users():
    page = request.args.get('page', 1, type=int)
    # Optimization: Eager load roles to prevent N+1 queries in the user list template
    stmt = db.select(User).options(joinedload(User.roles))
    users = db.paginate(stmt, page=page, per_page=15)
    return render_template('admin/manage_users.html', users=users)

@admin_bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@require_superuser()
def create_user():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email')
        full_name = request.form.get('full_name')
        role_id = request.form.get('role_id', type=int)
        location_id = request.form.get('location_id', type=int)

        if not all([username, password, full_name, location_id]):
            flash(_('All fields are required.'), 'error')
            return redirect(url_for('admin.create_user'))

        if len(password) < 8:
            flash(_('Password must be at least 8 characters'), 'error')
            return redirect(url_for('admin.create_user'))

        if db.session.execute(db.select(User).filter_by(username=username)).scalar():
            flash(_('Username already exists'), 'error')
        else:
            new_user = User(
                username=username,
                email=email,
                full_name=full_name,
                location_id=location_id
            )
            new_user.set_password(password)
            
            if role_id:
                role = db.session.get(Role, role_id)
                if role:
                    new_user.roles.append(role)
            
            db.session.add(new_user)
            db.session.commit()
            flash(_('User created successfully'), 'success')
            return redirect(url_for('admin.manage_users'))
    
    roles = db.session.execute(db.select(Role)).scalars().all()
    locations = db.session.execute(db.select(Location)).scalars().all()
    return render_template('admin/create_user.html', roles=roles, locations=locations)

@admin_bp.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@require_superuser()
def edit_user(user_id):
    user = db.session.get(User, user_id)
    if request.method == 'POST':
        user.full_name = request.form.get('full_name')
        user.email = request.form.get('email')
        user.is_active = 'is_active' in request.form
        user.location_id = request.form.get('location_id', type=int)
        
        # Update roles
        role_id = request.form.get('role_id', type=int)
        if role_id:
            role = db.session.get(Role, role_id)
            user.roles = [role] if role else []

        password = request.form.get('password')
        if password:
            if len(password) < 8:
                flash(_('Password must be at least 8 characters'), 'error')
                return redirect(url_for('admin.edit_user', user_id=user_id))
            user.set_password(password)
            
        db.session.commit()
        flash(_('User updated'), 'success')
        return redirect(url_for('admin.manage_users'))
    
    roles = db.session.execute(db.select(Role)).scalars().all()
    locations = db.session.execute(db.select(Location)).scalars().all()
    return render_template('admin/edit_user.html', user=user, roles=roles, locations=locations)

@admin_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
@require_superuser()
def delete_user(user_id):
    """Permanent removal of a staff account with safety checks"""
    if current_user.id == user_id:
        flash(_('Security Error: You cannot delete your own account.'), 'error')
        return redirect(url_for('admin.manage_users'))

    user = db.session.get(User, user_id)
    if user:
        db.session.delete(user)
        db.session.commit()
        flash(_('User account permanently removed.'), 'success')
    
    return redirect(url_for('admin.manage_users'))

@admin_bp.route('/locations', methods=['GET', 'POST'])
@login_required
@require_superuser()
def manage_locations():
    if request.method == 'POST':
        name = request.form.get('name')
        address = request.form.get('address')
        phone = request.form.get('phone')
        email = request.form.get('email')

        if name:
            new_loc = Location(name=name, address=address, phone=phone, email=email)
            db.session.add(new_loc)
            db.session.commit()
            flash(_('New location "%(name)s" created successfully.', name=name), 'success')
            return redirect(url_for('admin.manage_locations'))
        flash(_('Location name is required.'), 'error')

    locations = db.session.execute(db.select(Location)).scalars().all()
    return render_template('admin/locations.html', locations=locations)

@admin_bp.route('/inventory/parts')
@login_required
@require_permission('manage_settings')
def manage_inventory():
    """Dedicated inventory management for spare parts and stock levels"""
    page = request.args.get('page', 1, type=int)
    stmt = db.select(SparePart).filter_by(location_id=current_user.location_id).order_by(SparePart.name)
    parts = db.paginate(stmt, page=page, per_page=15)
    return render_template('admin/manage_parts.html', parts=parts)

@admin_bp.route('/inventory/parts/add', methods=['POST'])
@login_required
@require_permission('manage_settings')
def add_part_admin():
    """Endpoint for creating a new catalog part"""
    name = request.form.get('name')
    stock = request.form.get('stock_quantity', 0, type=int)

    if not name:
        flash(_('Part name is required.'), 'error')
        return redirect(url_for('admin.manage_inventory'))

    # Integrity: Check for duplicate names at this location
    exists = db.session.execute(db.select(SparePart).filter_by(
        name=name, 
        location_id=current_user.location_id
    )).scalar()
    if exists:
        flash(_('A part with this name already exists in your inventory.'), 'warning')
        return redirect(url_for('admin.manage_inventory'))

    if stock < 0:
        flash(_('Stock quantity cannot be negative.'), 'error')
        return redirect(url_for('admin.manage_inventory'))

    new_part = SparePart(
        name=name,
        cost=safe_decimal(request.form.get('cost')),
        selling_price=safe_decimal(request.form.get('selling_price')),
        stock_quantity=stock,
        location_id=current_user.location_id
    )
    db.session.add(new_part)
    db.session.commit()
    flash(_('New part added to inventory.'), 'success')
    return redirect(url_for('admin.manage_inventory'))

@admin_bp.route('/inventory/parts/edit/<int:part_id>', methods=['POST'])
@login_required
@require_permission('manage_settings')
def edit_part_admin(part_id):
    """Endpoint for updating existing part specifications"""
    part = db.session.get(SparePart, part_id)
    if not part or (not current_user.is_superuser and part.location_id != current_user.location_id):
        flash(_('Part not found.'), 'error')
        return redirect(url_for('admin.manage_inventory'))

    name = request.form.get('name')
    stock = request.form.get('stock_quantity', 0, type=int)

    if not name:
        flash(_('Part name is required.'), 'error')
        return redirect(url_for('admin.manage_inventory'))

    # Integrity: Check for duplicate names if the name was changed
    if name != part.name:
        exists = db.session.execute(db.select(SparePart).filter_by(
            name=name, 
            location_id=current_user.location_id
        )).scalar()
        if exists:
            flash(_('Another part already uses this name.'), 'warning')
            return redirect(url_for('admin.manage_inventory'))

    if stock < 0:
        flash(_('Stock quantity cannot be negative.'), 'error')
        return redirect(url_for('admin.manage_inventory'))

    part.name = name
    part.cost = safe_decimal(request.form.get('cost'))
    part.selling_price = safe_decimal(request.form.get('selling_price'))
    part.stock_quantity = stock
    part.is_active = 'is_active' in request.form
    
    db.session.commit()
    flash(_('Inventory item updated.'), 'success')
    return redirect(url_for('admin.manage_inventory'))

@admin_bp.route('/inventory/parts/delete/<int:part_id>', methods=['POST'])
@login_required
@require_permission('manage_settings')
def delete_part_admin(part_id):
    """Endpoint for permanent removal of inventory items"""
    part = db.session.get(SparePart, part_id)
    if part and (current_user.is_superuser or part.location_id == current_user.location_id):
        db.session.delete(part)
        db.session.commit()
        flash(_('Part deleted.'), 'success')
    return redirect(url_for('admin.manage_inventory'))

@admin_bp.route('/inventory/services')
@login_required
@require_permission('manage_settings')
def manage_services():
    """Catalog of labor services offered by the shop"""
    page = request.args.get('page', 1, type=int)
    stmt = db.select(Service).filter_by(location_id=current_user.location_id).order_by(Service.name)
    services = db.paginate(stmt, page=page, per_page=15)
    return render_template('admin/manage_services.html', services=services)

@admin_bp.route('/inventory/services/add', methods=['POST'])
@login_required
@require_permission('manage_settings')
def add_service_admin():
    """Endpoint to add a new service to the catalog"""
    name = request.form.get('name')
    if not name:
        flash(_('Service name is required.'), 'error')
        return redirect(url_for('admin.manage_services'))

    # Integrity: Check for duplicate services at this location
    exists = db.session.execute(db.select(Service).filter_by(
        name=name, 
        location_id=current_user.location_id
    )).scalar()
    if exists:
        flash(_('A service with this name already exists in your catalog.'), 'warning')
        return redirect(url_for('admin.manage_services'))

    new_service = Service(
        name=name,
        description=request.form.get('description'),
        price=safe_decimal(request.form.get('price')),
        location_id=current_user.location_id
    )
    db.session.add(new_service)
    db.session.commit()
    flash(_('Service added to catalog.'), 'success')
    return redirect(url_for('admin.manage_services'))

@admin_bp.route('/inventory/services/edit/<int:service_id>', methods=['POST'])
@login_required
@require_permission('manage_settings')
def edit_service_admin(service_id):
    """Endpoint for the dynamic edit modal in main.js"""
    service = db.session.get(Service, service_id)
    if not service or (not current_user.is_superuser and service.location_id != current_user.location_id):
        flash(_('Service not found.'), 'error')
        return redirect(url_for('admin.manage_services'))

    name = request.form.get('name')
    if not name:
        flash(_('Service name is required.'), 'error')
        return redirect(url_for('admin.manage_services'))

    # Integrity: Check for duplicate names if changed
    if name != service.name:
        exists = db.session.execute(db.select(Service).filter_by(
            name=name, 
            location_id=current_user.location_id
        )).scalar()
        if exists:
            flash(_('Another service already uses this name.'), 'warning')
            return redirect(url_for('admin.manage_services'))

    service.name = name
    service.description = request.form.get('description')
    service.price = safe_decimal(request.form.get('price'))
    service.is_active = 'is_active' in request.form
    
    db.session.commit()
    flash(_('Service updated.'), 'success')
    return redirect(url_for('admin.manage_services'))

@admin_bp.route('/inventory/services/delete/<int:service_id>', methods=['POST'])
@login_required
@require_permission('manage_settings')
def delete_service_admin(service_id):
    """Permanent removal of service from catalog"""
    service = db.session.get(Service, service_id)
    if service and (current_user.is_superuser or service.location_id == current_user.location_id):
        db.session.delete(service)
        db.session.commit()
        flash(_('Service deleted.'), 'success')
    return redirect(url_for('admin.manage_services'))

@admin_bp.route('/status')
@login_required
@require_superuser()
def system_status():
    """Comprehensive diagnostic view for administrators"""
    import sys
    import platform
    from sqlalchemy import text
    
    # 1. Database Check
    db_status = "Online"
    db_version = "Unknown"
    try:
        db_version = db.session.execute(text("SELECT version()")).scalar()
    except Exception:
        db_status = "Offline"

    # 2. Directory Permissions
    dirs = {
        'Logs': current_app.config['LOG_FILE'],
        'Backups': current_app.config['BACKUP_DIR'],
        'Uploads': current_app.config['UPLOAD_DIR']
    }
    dir_status = {}
    for name, path in dirs.items():
        folder = os.path.dirname(path) if name == 'Logs' else path
        dir_status[name] = {
            'path': folder,
            'writable': os.access(folder, os.W_OK)
        }

    # 3. System Info
    sys_info = {
        'os': f"{platform.system()} {platform.release()}",
        'python': sys.version.split()[0],
        'flask_env': os.getenv('FLASK_CONFIG', 'development'),
        'timezone': datetime.now().astimezone().tzname()
    }

    # 4. Config Summary (Masked)
    config_summary = {
        'Log Level': current_app.config['LOG_LEVEL'],
        'Backup Schedule': f"{current_app.config['BACKUP_HOUR']:02d}:{current_app.config['BACKUP_MINUTE']:02d} UTC",
        'Session Lifetime': f"{current_app.config['PERMANENT_SESSION_LIFETIME'].total_seconds() / 3600} hours"
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
            data = BackupService.get_system_logical_data()
            filename = f"manual_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            path = os.path.join(current_app.config['BACKUP_DIR'], filename)
            with open(path, 'w') as f:
                json.dump(data, f)
            flash(_('Logical backup created successfully: %(name)s', name=filename), 'success')
        elif backup_type == 'full_db':
            filename = f"full_dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dump"
            path = os.path.join(current_app.config['BACKUP_DIR'], filename)
            
            try:
                db_url = current_app.config['SQLALCHEMY_DATABASE_URI']
                
                if 'postgresql' in db_url:
                    # System tools don't support SQLAlchemy driver syntax (e.g. +psycopg)
                    clean_url = db_url.replace('+psycopg', '')
                    
                    # Capture stderr to provide helpful feedback if pg_dump fails
                    subprocess.run(['pg_dump', '--dbname', clean_url, '-Fc', '-f', path], 
                                   check=True, capture_output=True)
                    flash(_('Full database snapshot created successfully: %(name)s', name=filename), 'success')
                else:
                    flash(_('Full snapshots are only supported for PostgreSQL installations.'), 'warning')
            except subprocess.CalledProcessError as e:
                err_msg = e.stderr.decode() if e.stderr else _("Process returned non-zero exit status.")
                flash(_('Error: pg_dump failed. %(msg)s', msg=err_msg), 'error')
            except Exception as e:
                current_app.logger.error(f"Backup failed: {str(e)}")
                flash(_('An unexpected error occurred during the backup process.'), 'error')

        return redirect(url_for('admin.backup'))

    backup_dir = current_app.config['BACKUP_DIR']
    backups = sorted(os.listdir(backup_dir), reverse=True) if os.path.exists(backup_dir) else []
    return render_template('admin/backup.html', backups=backups)

@admin_bp.route('/backup/download/<filename>')
@login_required
@require_superuser()
def download_backup_file(filename):
    """Download a backup file from the server's repository"""
    path = os.path.join(current_app.config['BACKUP_DIR'], filename)
    if os.path.exists(path):
        return send_file(path, as_attachment=True)
    flash(_('File not found.'), 'error')
    return redirect(url_for('admin.backup'))

@admin_bp.route('/backup/restore', methods=['POST'])
@login_required
@require_superuser()
def restore():
    if 'backup_file' not in request.files:
        flash(_('No file uploaded.'), 'error')
        return redirect(url_for('admin.backup'))
    
    file = request.files['backup_file']
    if file.filename == '':
        flash(_('No file selected.'), 'error')
        return redirect(url_for('admin.backup'))

    if file and file.filename.endswith('.dump'):
        filename = secure_filename(file.filename)
        temp_path = os.path.join(current_app.config['BACKUP_DIR'], f"temp_{filename}")
        file.save(temp_path)
        
        success, message = BackupService.restore_full_backup(temp_path)
        if os.path.exists(temp_path): os.remove(temp_path)
        
        if success:
            flash(_('Database restored successfully. System state has been reverted.'), 'success')
        else:
            flash(message, 'error')
    else:
        flash(_('Only .dump files (PostgreSQL binary) are supported for automated restore.'), 'warning')

    return redirect(url_for('admin.backup'))

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@require_permission('manage_settings')
def settings():
    shop_settings = db.session.execute(db.select(ShopSetting).filter_by(location_id=current_user.location_id)).scalar()
    if request.method == 'POST':
        if not shop_settings:
            shop_settings = ShopSetting(location_id=current_user.location_id)
            db.session.add(shop_settings)
        
        shop_settings.shop_name = request.form.get('shop_name')
        shop_settings.shop_address = request.form.get('shop_address')
        shop_settings.shop_phone = request.form.get('shop_phone')
        shop_settings.shop_email = request.form.get('shop_email')

        # Handle Logo Upload
        file = request.files.get('shop_logo')
        if file and file.filename:
            filename = secure_filename(f"logo_loc_{current_user.location_id}_{file.filename}")
            logo_dir = current_app.config['LOGOS_DIR']
            
            # Remove old logo if it exists
            if shop_settings.logo_path:
                old_path = os.path.join(logo_dir, shop_settings.logo_path)
                if os.path.exists(old_path): os.remove(old_path)
            
            file.save(os.path.join(logo_dir, filename))
            shop_settings.logo_path = filename
        
        db.session.commit()
        flash(_('Settings updated successfully!'), 'success')
        return redirect(url_for('admin.settings'))
        
    return render_template('admin/settings.html', settings=shop_settings)

@admin_bp.route('/backup/export')
@login_required
@require_superuser()
def export_backup():
    """Manual trigger for system backup data"""
    data = BackupService.get_system_logical_data()
    return jsonify(data)