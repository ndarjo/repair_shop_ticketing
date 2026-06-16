import click
import os
from flask.cli import with_appcontext
from models import db, Role, Permission, User, Location, CommonProblem, Customer, ShopSetting
from cryptography.fernet import Fernet
from sqlalchemy import func, text
from flask_babel import _

def initialize_roles_and_permissions():
    """Create default system roles and assign granular permissions."""
    # INTEGRITY: Ensure the database schema is in sync with models for production readiness.
    # This proactively fixes 'UndefinedColumn' errors during system updates by adding missing columns.
    try:
        with db.engine.connect() as conn:
            # Postgres-compatible schema patching for ShopSetting columns
            conn.execute(text("ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS currency VARCHAR(10) DEFAULT 'USD' NOT NULL"))
            conn.execute(text("ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS currency_decimals INTEGER DEFAULT 2 NOT NULL"))
            conn.execute(text("ALTER TABLE shop_settings ADD COLUMN IF NOT EXISTS location_id INTEGER REFERENCES locations(id)"))
            conn.commit()
    except Exception:
        # Fallback or silent skip for SQLite environments during testing/development
        try: db.session.rollback()
        except: pass

    permissions = [
        'view_customer', 'create_customer', 'edit_customer', 'delete_customer', 'export_customer',
        'view_ticket', 'create_ticket', 'edit_ticket', 'delete_ticket', 'archive_ticket',
        'view_reports', 'manage_settings', 'process_payments', 'manage_inventory',
        'view_inventory', 'view_services',
        'view_device', 'create_device', 'edit_device', 'delete_device', 'create_invoice',
        # Admin Panel Specific Permissions (ensure comma after each item)
        'admin_access_dashboard', 'admin_manage_locations', 'admin_manage_users', 
        'admin_manage_backups', 'admin_view_system_status', 'admin_manage_branding', 'admin_manage_common_problems',
        # Other ticket-related permissions
        'update_phase', 'mark_as_paid', 'mark_as_taken',
        'add_service', 'remove_service', 'add_part', 'remove_part',
        'process_sales'
    ]
    
    perm_objs = {}
    for p_name in permissions:
        perm = db.session.scalar(db.select(Permission).where(Permission.name == p_name))
        if not perm:
            perm = Permission(name=p_name, category=_('General'))
            db.session.add(perm)
        perm_objs[p_name] = perm
    db.session.flush()

    role_permissions = {
        'admin': permissions,
        'manager': [
            'view_customer', 'create_customer', 'edit_customer', 'export_customer', 'delete_customer',
            'view_inventory', 'view_services',
            'view_device', 'create_device', 'edit_device', 'delete_device',
            'view_ticket', 'create_ticket', 'edit_ticket', 'archive_ticket', 'update_phase',
            'manage_inventory', 'add_service', 'remove_service', 'add_part', 'remove_part',
            'process_payments', 'process_sales', 'create_invoice',
            'view_reports', 'manage_settings',
            'admin_access_dashboard', 'admin_manage_users', 
            'admin_view_system_status', 'admin_manage_backups',
            'admin_manage_common_problems'
        ],
        'technician': [
            'view_inventory', 'view_services',
            'view_customer', 'view_ticket', 'view_device', 'edit_device', 'edit_ticket', 
            'update_phase', 
            'add_service', 'remove_service', 'add_part', 'remove_part'
        ],
        'receptionist': [
            'view_inventory', 'view_services',
            'view_customer', 'create_customer', 'view_ticket', 'create_ticket',
            'view_device', 'create_device', 'edit_device', 'edit_ticket', 
            'create_invoice',
            'process_payments', 'mark_as_paid', 'mark_as_taken',
            'add_service', 'remove_service', 'add_part', 'remove_part',
            'process_sales'
        ]
    }

    for role_name, perms in role_permissions.items():
        role = db.session.scalar(db.select(Role).where(Role.name == role_name))
        if not role:
            role = Role(name=role_name)
            db.session.add(role)
        role.permissions = [perm_objs[p] for p in perms]
    
    db.session.commit()

def initialize_default_data():
    """Seed the database with common repair problems and a default location."""
    main_loc = db.session.scalar(db.select(Location))
    if not main_loc:
        main_loc = Location(name=_("Main Branch"), address="123 System Ave")
        db.session.add(main_loc)
        db.session.flush() # Get ID for problem linking

        # SEEDING: Only add default problems during the initial creation of the first branch.
        # This prevents deleted default items from being re-added every time the server restarts.
        problems = [
            _('Broken Screen'), _('Battery Replacement'), _('Water Damage'),
            _('Charging Port Issue'), _('Software Failure'), _('No Power'),
            _('Data Recovery'), _('Keyboard Replacement')
        ]
        
        for p_text in problems:
            exists = db.session.scalar(db.select(CommonProblem).where(
                func.lower(CommonProblem.problem_text) == func.lower(p_text), 
                CommonProblem.location_id == main_loc.id))
            if not exists:
                db.session.add(CommonProblem(problem_text=p_text, location_id=main_loc.id))

    # INTEGRITY: Ensure the global ShopSetting record exists so custom branding is preserved.
    # We check if any record exists at all before seeding the default one.
    if not db.session.scalar(db.select(ShopSetting)):
        db.session.add(ShopSetting(
            shop_name=_("Repair Shop"),
            setup_completed=False,
            location_id=main_loc.id if main_loc else None
        ))

    db.session.commit()

def initialize_superuser():
    """Ensure at least one admin exists based on environment variables."""
    admin_user = db.session.scalar(db.select(User).where(User.is_superuser == True))
    if not admin_user:
        main_loc = db.session.scalar(db.select(Location))
        username = os.getenv('INITIAL_ADMIN_USERNAME') or 'admin'
        
        # INTEGRITY: Prevent silent failure if the intended admin username is taken by a non-superuser
        if db.session.scalar(db.select(User).where(func.lower(User.username) == func.lower(username))):
            raise ValueError(_("Initial admin username '%(username)s' is already taken by a non-superuser. System cannot initialize safely.", username=username))

        admin = User(
            username=username,
            full_name=_('System Administrator'),
            is_superuser=True,
            is_active=True,
            location_id=main_loc.id if main_loc else None
        )
        
        initial_password = os.getenv('INITIAL_ADMIN_PASSWORD') or 'change-me-immediately'
        if len(initial_password) < 8:
            initial_password = 'change-me-immediately' # Fallback to a secure default if ENV is weak
            
        admin.set_password(initial_password)
        
        admin_role = db.session.scalar(db.select(Role).where(Role.name == 'admin'))
        if admin_role:
            admin.roles.append(admin_role)
            
        db.session.add(admin)
        db.session.commit()

def register_cli_commands(app):
    """Register custom Flask CLI commands."""
    @app.cli.command("seed")
    @with_appcontext
    def seed():
        try:
            initialize_roles_and_permissions()
            initialize_default_data()
            initialize_superuser() # Ensure admin account is created alongside data
            click.echo(_("Database seeded."))
        except Exception as e:
            db.session.rollback()
            click.echo(_("Error during seeding: %(error)s", error=str(e) or e.__class__.__name__), err=True)

    @app.cli.command("reencrypt-pii")
    @click.option("--old-key", prompt=True, hide_input=True, help=_("The old ENCRYPTION_KEY to decrypt existing data."))
    @with_appcontext
    def reencrypt(old_key):
        """Rotate encryption keys: Decrypts data using the provided OLD_KEY and re-encrypts using the current system key."""
        try:
            old_fernet = Fernet(old_key.encode())
            customers = db.session.scalars(db.select(Customer))
            count = 0
            for customer in customers:
                modified = False
                # Manually decrypt phone/address using the provided old key
                # then set them back so the model's @property.setter re-encrypts with the NEW key
                if customer._phone_encrypted:
                    decrypted_phone = old_fernet.decrypt(customer._phone_encrypted.encode()).decode()
                    customer.phone = decrypted_phone
                    modified = True
                
                if customer._address_encrypted:
                    decrypted_address = old_fernet.decrypt(customer._address_encrypted.encode()).decode()
                    customer.address = decrypted_address
                    modified = True
                
                if modified:
                    count += 1
            
            db.session.commit()
            click.echo(_("Successfully re-encrypted PII for %(count)d customers.", count=count))
        except Exception as e:
            db.session.rollback()
            click.echo(_("Error during re-encryption: %(error)s", error=str(e) or e.__class__.__name__), err=True)

    @app.cli.command("create-user")
    @click.argument("username")
    @click.password_option(help=_("The password for the new user."))
    @click.option("--role", default="technician", help=_("System role to assign (admin, manager, technician, receptionist)."))
    @click.option("--full-name", default="", help=_("Display name for the user."))
    @with_appcontext
    def create_user(username, password, role, full_name):
        """Create a new user with a specific role."""
        if len(password) < 8:
            click.echo(_("Error: Password must be at least 8 characters."), err=True)
            return

        if db.session.scalar(db.select(User).where(func.lower(User.username) == func.lower(username))):
            click.echo(_("Error: User %(username)s already exists.", username=username), err=True)
            return
            
        role_obj = db.session.scalar(db.select(Role).where(func.lower(Role.name) == func.lower(role)))
        if not role_obj:
            click.echo(_("Error: Role %(role)s does not exist.", role=role), err=True)
            return
            
        loc = db.session.scalar(db.select(Location))
        user = User(
            username=username, 
            full_name=full_name,
            is_active=True, 
            location_id=loc.id if loc else None
        )
        user.set_password(password)
        if role_obj.name == 'admin':
            user.is_superuser = True
        user.roles.append(role_obj)
        try:
            db.session.add(user)
            db.session.commit()
            click.echo(_("User %(username)s created successfully.", username=username))
        except Exception as e:
            db.session.rollback()
            click.echo(_("Error creating user: %(error)s", error=str(e)), err=True)

    @app.cli.command("reset-db")
    @with_appcontext
    def reset_db():
        """Wipe and re-initialize the database."""
        if click.confirm(_('CRITICAL: This will PERMANENTLY WIPE all database tables and data. Continue?'), abort=True):
            db.drop_all()
            db.create_all()
            click.echo(_("Database reset complete."))

def register_scheduler_tasks(scheduler, app):
    """Register background tasks for the APScheduler."""
    h = app.config.get('BACKUP_HOUR', 2)
    m = app.config.get('BACKUP_MINUTE', 0)

    @scheduler.task('cron', id='daily_backup', hour=h, minute=m)
    def daily_backup():
        with app.app_context():
            from services.backup import BackupService
            success, message = BackupService.run_automated_backup()
            if success:
                app.logger.info(message)
            else:
                app.logger.error(message)