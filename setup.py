import os
import click
from datetime import datetime
from flask.cli import with_appcontext
from sqlalchemy import select
from models import db, User, Role, Permission, CommonProblem, Location, ShopSetting
from flask_babel import _

def initialize_roles_and_permissions():
    """Create default system roles and assign granular permissions."""
    permissions = [
        'view_customer', 'create_customer', 'edit_customer', 'delete_customer',
        'view_ticket', 'create_ticket', 'edit_ticket', 'delete_ticket',
        'view_reports', 'manage_settings', 'process_payments', 'manage_inventory',
        'create_device', 'edit_device', 'delete_device'
    ]
    
    # Create permissions if they don't exist
    perm_objs = {}
    for p_name in permissions:
        stmt = select(Permission).where(Permission.name == p_name)
        perm = db.session.scalar(stmt)
        if not perm:
            perm = Permission(name=p_name)
            db.session.add(perm)
        perm_objs[p_name] = perm
    db.session.flush()

    # Define Role Mapping
    role_permissions = {
        'admin': permissions,
        'manager': [p for p in permissions if 'delete' not in p or 'customer' in p],
        'technician': ['view_customer', 'view_ticket', 'edit_ticket', 'manage_inventory', 'create_device', 'edit_device'],
        'receptionist': ['view_customer', 'create_customer', 'view_ticket', 'create_ticket', 'process_payments']
    }

    for role_name, perms in role_permissions.items():
        stmt = select(Role).where(Role.name == role_name)
        role = db.session.scalar(stmt)
        if not role:
            role = Role(name=role_name)
            db.session.add(role)
        
        # Assign permissions to role
        role.permissions = [perm_objs[p] for p in perms]
    
    db.session.commit()

def initialize_default_data():
    """Seed the database with common repair problems."""
    problems = [
        _('Broken Screen'), _('Battery Replacement'), _('Water Damage'),
        _('Charging Port Issue'), _('Software Failure'), _('No Power'),
        _('Data Recovery'), _('Keyboard Replacement')
    ]
    
    for p_name in problems:
        stmt = select(CommonProblem).where(CommonProblem.name == p_name)
        if not db.session.scalar(stmt):
            db.session.add(CommonProblem(name=p_name))
    db.session.commit()

def initialize_superuser():
    """Ensure at least one admin exists based on environment variables."""
    stmt = select(User).where(User.is_superuser == True)
    admin_user = db.session.scalar(stmt)
    if not admin_user:
        # Create a default location for the first user
        main_loc = db.session.scalar(select(Location))
        if not main_loc:
            main_loc = Location(name="Main Branch")
            db.session.add(main_loc)
            db.session.flush()

        username = os.getenv('INITIAL_ADMIN_USERNAME', 'admin')
        password = os.getenv('INITIAL_ADMIN_PASSWORD', 'change-me-immediately')
        
        admin = User(
            username=username,
            is_superuser=True,
            is_active=True,
            location_id=main_loc.id
        )
        admin.set_password(password)
        
        # Assign admin role
        role_stmt = select(Role).where(Role.name == 'admin')
        admin_role = db.session.scalar(role_stmt)
        if admin_role:
            admin.roles.append(admin_role)
            
        db.session.add(admin)
        db.session.commit()

def register_scheduler_tasks(scheduler, app):
    """Register recurring background tasks."""
    
    @scheduler.task('cron', id='daily_backup', hour=2, minute=0)
    def daily_backup():
        with app.app_context():
            from services.core import BackupService
            app.logger.info("Starting scheduled daily backup...")
            success, path = BackupService.create_automated_backup()
            if success:
                app.logger.info(f"Backup completed successfully: {path}")
            else:
                app.logger.error("Scheduled backup failed.")

def register_cli_commands(app):
    """Register custom Flask CLI commands."""
    
    @app.cli.command("create-user")
    @click.argument("username")
    @click.argument("password")
    @click.option("--role", default="technician")
    @with_appcontext
    def create_user(username, password, role):
        """Create a new user with a specific role."""
        if db.session.scalar(select(User).where(User.username == username)):
            print(f"User {username} already exists.")
            return
            
        role_obj = db.session.scalar(select(Role).where(Role.name == role))
        if not role_obj:
            print(f"Role {role} does not exist.")
            return
            
        loc = db.session.scalar(select(Location))
        user = User(username=username, is_active=True, location_id=loc.id if loc else None)
        user.set_password(password)
        user.roles.append(role_obj)
        db.session.add(user)
        db.session.commit()
        print(f"User {username} created successfully.")

    @app.cli.command("reset-db")
    @with_appcontext
    def reset_db():
        """Wipe and re-initialize the database."""
        db.drop_all()
        db.create_all()
        print("Database reset complete.")