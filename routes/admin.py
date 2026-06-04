from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from models import db, User, Role, Location, ShopSetting, Permission
from services import BackupService
from .utils import require_permission, require_superuser
from flask_babel import _

admin_bp = Blueprint('admin', __name__)
onboarding_bp = Blueprint('onboarding', __name__)

def get_logical_backup_data():
    """Bridge function for the backup service used by CLI/Tasks"""
    return BackupService.get_system_logical_data()

# ==================== ADMIN ROUTES ====================

@admin_bp.route('/users')
@login_required
@require_superuser
def manage_users():
    users = User.query.all()
    return render_template('admin/users.html', users=users)

@admin_bp.route('/locations')
@login_required
@require_superuser
def manage_locations():
    locations = Location.query.all()
    return render_template('admin/locations.html', locations=locations)

@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@require_permission('manage_settings')
def settings():
    shop_settings = ShopSetting.query.filter_by(location_id=current_user.location_id).first()
    if request.method == 'POST':
        if not shop_settings:
            shop_settings = ShopSetting(location_id=current_user.location_id)
            db.session.add(shop_settings)
        
        shop_settings.shop_name = request.form.get('shop_name')
        shop_settings.shop_address = request.form.get('shop_address')
        shop_settings.shop_phone = request.form.get('shop_phone')
        shop_settings.shop_email = request.form.get('shop_email')
        
        db.session.commit()
        flash(_('Settings updated successfully!'), 'success')
        return redirect(url_for('admin.settings'))
        
    return render_template('admin/settings.html', settings=shop_settings)

# ==================== ONBOARDING ROUTES ====================

@onboarding_bp.route('/setup', methods=['GET', 'POST'])
@login_required
def setup():
    """Initial shop setup for superusers"""
    if not current_user.is_superuser:
        return redirect(url_for('main.dashboard'))
        
    shop_settings = ShopSetting.query.first()
    if shop_settings and shop_settings.setup_completed:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        if not shop_settings:
            # Create default location if none exists
            loc = Location.query.first()
            if not loc:
                loc = Location(name=_('Main Branch'))
                db.session.add(loc)
                db.session.flush()
            
            shop_settings = ShopSetting(location_id=loc.id)
            db.session.add(shop_settings)
            
            # Link user to location
            current_user.location_id = loc.id

        shop_settings.shop_name = request.form.get('shop_name')
        shop_settings.setup_completed = True
        db.session.commit()
        
        flash(_('Welcome! Shop setup is complete.'), 'success')
        return redirect(url_for('main.dashboard'))
        
    return render_template('onboarding/setup.html')

@admin_bp.route('/backup/export')
@login_required
@require_superuser
def export_backup():
    """Manual trigger for system backup data"""
    data = get_logical_backup_data()
    return jsonify(data)