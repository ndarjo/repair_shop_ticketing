from babel.numbers import list_currencies, get_currency_name
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_babel import _, get_locale
from flask_login import current_user, login_required

from models import Location, ShopSetting, db
from .utils import require_superuser

onboarding_bp = Blueprint('onboarding', __name__)

@onboarding_bp.route('/setup', methods=['GET', 'POST'])
@login_required
@require_superuser()
def setup():
    """Initial shop setup for superusers"""
    shop_settings = None
    try:
        # INTEGRITY: Robust lookup for multi-tenancy. 
        # Fetch specific branch settings first, fallback to global settings.
        loc_id = current_user.location_id
        shop_settings = db.session.scalar(db.select(ShopSetting).filter_by(location_id=loc_id))
        if not shop_settings:
            shop_settings = db.session.scalar(db.select(ShopSetting).filter_by(location_id=None))
            
    except Exception:
        db.session.rollback()
        flash(_('Database schema is outdated. Please run "flask seed" to synchronize system tables.'), 'danger')
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
            shop_settings.currency = currency or 'USD'
            shop_settings.currency_decimals = request.form.get('currency_decimals', type=int, default=2)

            # Sync User Preferences with Setup Choices
            if language in current_app.config['LANGUAGES']:
                current_user.language_preference = language
                session['language'] = language # UX Sync: Update current session language immediately

            if currency in list_currencies():
                current_user.currency = currency
                current_user.currency_decimals = shop_settings.currency_decimals

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
        
    # Prepare localized currency list for the dropdown
    all_currencies = [(code, f"{code} - {get_currency_name(code, locale=get_locale())}") 
                      for code in list_currencies()]
    all_currencies.sort(key=lambda x: x[1])

    return render_template('onboarding/setup.html',
                           settings=shop_settings,
                           all_currencies=all_currencies,
                           shop_name=shop_settings.shop_name if shop_settings else _('Repair Shop'),
                           shop_address=shop_settings.shop_address if shop_settings else '',
                           shop_phone=shop_settings.shop_phone if shop_settings else '',
                           shop_email=shop_settings.shop_email if shop_settings else '',
                           selected_language=current_user.language_preference or session.get('language'),
                           selected_currency=shop_settings.currency if shop_settings else current_user.currency,
                           selected_currency_decimals=shop_settings.currency_decimals if shop_settings else 2)