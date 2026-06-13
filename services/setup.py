import click
import os
from flask.cli import with_appcontext
from models import db, Role, Permission, User, Location, CommonProblem, Customer
from cryptography.fernet import Fernet
from sqlalchemy import func

def initialize_roles_and_permissions():
    """Create default system roles and assign granular permissions."""
    permissions = [
        'view_customer', 'create_customer', 'edit_customer', 'delete_customer',
        'view_ticket', 'create_ticket', 'edit_ticket', 'delete_ticket', 'archive_ticket',
        'view_reports', 'manage_settings', 'process_payments', 'manage_inventory',
        'view_device', 'create_device', 'edit_device', 'delete_device', 'create_invoice',
        'update_phase', 'mark_as_paid', 'mark_as_taken',
        'add_service', 'remove_service', 'add_part', 'remove_part'
    ]
    
    perm_objs = {}
    for p_name in permissions:
        perm = db.session.scalar(db.select(Permission).where(Permission.name == p_name))
        if not perm:
            perm = Permission(name=p_name, category='General')
            db.session.add(perm)
        perm_objs[p_name] = perm
    db.session.flush()

    role_permissions = {
        'admin': permissions,
        'manager': [p for p in permissions if p not in ['delete_ticket', 'delete_device']],
        'technician': [
            'view_customer', 'view_ticket', 'view_device', 'edit_device', 'edit_ticket', 
            'update_phase', 
            'add_service', 'remove_service', 'add_part', 'remove_part'
        ],
        'receptionist': [
            'view_customer', 'create_customer', 'view_ticket', 'create_ticket',
            'view_device', 'create_device', 'edit_device', 'edit_ticket', 
            'create_invoice',
            'process_payments', 'mark_as_paid', 'mark_as_taken',
            'add_service', 'remove_service', 'add_part', 'remove_part'
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
        main_loc = Location(name="Main Branch", address="123 System Ave")
        db.session.add(main_loc)
        db.session.flush() # Get ID for problem linking

    problems = [
        'Broken Screen', 'Battery Replacement', 'Water Damage',
        'Charging Port Issue', 'Software Failure', 'No Power',
        'Data Recovery', 'Keyboard Replacement'
    ]
    
    for p_text in problems:
        exists = db.session.scalar(db.select(CommonProblem).where(
            func.lower(CommonProblem.problem_text) == func.lower(p_text), 
            CommonProblem.location_id == main_loc.id))
        if not exists:
            db.session.add(CommonProblem(problem_text=p_text, location_id=main_loc.id))
    db.session.commit()

def initialize_superuser():
    """Ensure at least one admin exists based on environment variables."""
    admin_user = db.session.scalar(db.select(User).where(User.is_superuser == True))
    if not admin_user:
        main_loc = db.session.scalar(db.select(Location))
        username = os.getenv('INITIAL_ADMIN_USERNAME') or 'admin'
        
        # Bug Fix: Prevent crash if the intended admin username is taken by a non-superuser
        if db.session.scalar(db.select(User).where(func.lower(User.username) == func.lower(username))):
            return

        admin = User(
            username=username,
            full_name='System Administrator',
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
            click.echo("Database seeded.")
        except Exception as e:
            db.session.rollback()
            click.echo(f"Error during seeding: {str(e)}", err=True)

    @app.cli.command("reencrypt-pii")
    @click.argument("old_key")
    @with_appcontext
    def reencrypt(old_key):
        """Rotate encryption keys: Decrypts with OLD_KEY and re-encrypts with current config."""
        try:
            old_fernet = Fernet(old_key.encode())
            customers = db.session.scalars(db.select(Customer)).all()
            count = 0
            for customer in customers:
                # Manually decrypt phone/address using the provided old key
                # then set them back so the model's @property.setter re-encrypts with the NEW key
                if customer._phone_encrypted:
                    decrypted_phone = old_fernet.decrypt(customer._phone_encrypted.encode()).decode()
                    customer.phone = decrypted_phone
                
                if customer._address_encrypted:
                    decrypted_address = old_fernet.decrypt(customer._address_encrypted.encode()).decode()
                    customer.address = decrypted_address
                
                count += 1
            
            db.session.commit()
            click.echo(f"Successfully re-encrypted PII for {count} customers.")
        except Exception as e:
            db.session.rollback()
            click.echo(f"Error during re-encryption: {str(e)}", err=True)

    @app.cli.command("create-user")
    @click.argument("username")
    @click.argument("password")
    @click.option("--role", default="technician")
    @with_appcontext
    def create_user(username, password, role):
        """Create a new user with a specific role."""
        if len(password) < 8:
            click.echo("Error: Password must be at least 8 characters.", err=True)
            return

        if db.session.scalar(db.select(User).where(func.lower(User.username) == func.lower(username))):
            click.echo(f"Error: User {username} already exists.", err=True)
            return
            
        role_obj = db.session.scalar(db.select(Role).where(func.lower(Role.name) == func.lower(role)))
        if not role_obj:
            click.echo(f"Error: Role {role} does not exist.", err=True)
            return
            
        loc = db.session.scalar(db.select(Location))
        user = User(username=username, is_active=True, location_id=loc.id if loc else None)
        user.set_password(password)
        if role_obj.name == 'admin':
            user.is_superuser = True
        user.roles.append(role_obj)
        try:
            db.session.add(user)
            db.session.commit()
            click.echo(f"User {username} created successfully.")
        except Exception as e:
            db.session.rollback()
            click.echo(f"Error creating user: {str(e)}", err=True)

    @app.cli.command("reset-db")
    @with_appcontext
    def reset_db():
        """Wipe and re-initialize the database."""
        if click.confirm('CRITICAL: This will PERMANENTLY WIPE all database tables and data. Continue?', abort=True):
            db.drop_all()
            db.create_all()
            click.echo("Database reset complete.")

def register_scheduler_tasks(scheduler, app):
    """Register background tasks for the APScheduler."""
    h = app.config.get('BACKUP_HOUR', 2)
    m = app.config.get('BACKUP_MINUTE', 0)

    @scheduler.task('cron', id='daily_backup', hour=h, minute=m)
    def daily_backup():
        with app.app_context():
            from services.backup import BackupService
            success, message = BackupService.run_automated_backup()
            app.logger.info(message)