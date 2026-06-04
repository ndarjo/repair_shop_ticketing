from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from models import db, ShopSetting, Location
from flask_babel import _

onboarding_bp = Blueprint('onboarding', __name__)

@onboarding_bp.route('/setup', methods=['GET', 'POST'])
@login_required
def setup():
    """Initial shop setup for superusers"""
    if not current_user.is_superuser:
        return redirect(url_for('main.dashboard'))
        
    shop_settings = db.session.execute(db.select(ShopSetting)).scalar()
    if shop_settings and shop_settings.setup_completed:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        if not shop_settings:
            # Create default location if none exists
            loc = db.session.execute(db.select(Location)).scalar()
            if not loc:
                loc = Location(name=_('Main Branch'))
                db.session.add(loc)
                db.session.flush()
            
            shop_settings = ShopSetting(location_id=loc.id)
            db.session.add(shop_settings)
            
            # Link user to location
            current_user.location_id = loc.id

        shop_settings.shop_name = request.form.get('shop_name')
        shop_settings.shop_address = request.form.get('shop_address')
        shop_settings.shop_phone = request.form.get('shop_phone')
        shop_settings.shop_email = request.form.get('shop_email')

        # Sync User Preferences with Setup Choices
        language = request.form.get('language')
        if language in current_app.config['LANGUAGES']:
            current_user.language_preference = language

        currency = request.form.get('currency')
        if currency in ['USD', 'IDR', 'EUR', 'GBP']:
            current_user.currency = currency

        shop_settings.setup_completed = True
        db.session.commit()
        
        flash(_('Welcome! Shop setup is complete.'), 'success')
        return redirect(url_for('main.dashboard'))
        
    return render_template('onboarding/setup.html')