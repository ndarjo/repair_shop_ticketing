from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session
from flask_login import login_required, current_user
from models import db, ShopSetting, Location
from babel.numbers import list_currencies
from flask_babel import _

onboarding_bp = Blueprint('onboarding', __name__)

@onboarding_bp.route('/setup', methods=['GET', 'POST'])
@login_required
def setup():
    """Initial shop setup for superusers"""
    if not current_user.is_superuser:
        return redirect(url_for('main.dashboard'))
        
    shop_settings = db.session.scalar(db.select(ShopSetting))
    if shop_settings and shop_settings.setup_completed:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        shop_name = request.form.get('shop_name', '').strip()
        shop_address = request.form.get('shop_address', '').strip()
        shop_phone = request.form.get('shop_phone', '').strip()
        shop_email = request.form.get('shop_email', '').strip()
        language = request.form.get('language')
        currency = request.form.get('currency')

        if not shop_name:
            flash(_('Shop name is required.'), 'error')
            return render_template('onboarding/setup.html', 
                                   shop_name=shop_name, 
                                   shop_address=shop_address, 
                                   shop_phone=shop_phone, 
                                   shop_email=shop_email,
                                   selected_language=language, 
                                   selected_currency=currency)

        try:
            # INTEGRITY: Ensure a primary location exists and is linked to the setup
            loc = db.session.scalar(db.select(Location))
            if not loc:
                loc = Location(name=_('Main Branch'))
                db.session.add(loc)
                db.session.flush()
            
            # Sync Location record with Shop branding for consistency
            loc.name = shop_name
            loc.address = shop_address
            loc.phone = shop_phone
            loc.email = shop_email

            if not shop_settings:
                shop_settings = ShopSetting(location_id=loc.id)
                db.session.add(shop_settings)
            else:
                # Ensure existing settings are bound to the primary location
                shop_settings.location_id = loc.id

            # Always ensure the initializing superuser is bound to the branch
            current_user.location_id = loc.id

            shop_settings.shop_name = shop_name
            shop_settings.shop_address = shop_address
            shop_settings.shop_phone = shop_phone
            shop_settings.shop_email = shop_email

            # Sync User Preferences with Setup Choices
            if language in current_app.config['LANGUAGES']:
                current_user.language_preference = language

            if currency in list_currencies():
                current_user.currency = currency

            shop_settings.setup_completed = True
            db.session.commit()
            flash(_('Welcome! Shop setup is complete.'), 'success')
            return redirect(url_for('main.dashboard'))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Onboarding setup failed: {str(e)}")
            flash(_('An error occurred during setup. Please try again.'), 'error')
            return render_template('onboarding/setup.html', 
                                   shop_name=shop_name, 
                                   shop_address=shop_address, 
                                   shop_phone=shop_phone, 
                                   shop_email=shop_email,
                                   selected_language=language, 
                                   selected_currency=currency)
        
    return render_template('onboarding/setup.html',
                           shop_name=shop_settings.shop_name if shop_settings else '',
                           shop_address=shop_settings.shop_address if shop_settings else '',
                           shop_phone=shop_settings.shop_phone if shop_settings else '',
                           shop_email=shop_settings.shop_email if shop_settings else '',
                           selected_language=current_user.language_preference or session.get('language'),
                           selected_currency=current_user.currency)