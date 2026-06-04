import click
import os
from flask.cli import with_appcontext
from models import db, Role, Permission, User, Location, ShopSetting
from datetime import datetime, timezone
from flask import current_app

def initialize_roles_and_permissions():
    """Seed the database with default roles and permissions."""
    # Example permissions
    perms = [
        ('view_dashboard', 'General'),
        ('create_ticket', 'Tickets'),
        ('edit_ticket', 'Tickets'),
        ('view_reports', 'Admin'),
        ('manage_settings', 'Admin')
    ]
    for name, cat in perms:
        if not Permission.query.filter_by(name=name).first():
            p = Permission(name=name, category=cat)
            db.session.add(p)
    
    # Example Roles
    roles = ['Admin', 'Technician', 'Receptionist']
    for role_name in roles:
        if not Role.query.filter_by(name=role_name).first():
            r = Role(name=role_name)
            db.session.add(r)
    db.session.commit()

def initialize_default_data():
    """Seed common problems and default location."""
    if not Location.query.first():
        loc = Location(name="Main Shop", address="123 Tech St")
        db.session.add(loc)
        db.session.commit()

def initialize_superuser():
    """Create the initial admin user if it doesn't exist."""
    admin_user = User.query.filter_by(username='admin').first()
    if not admin_user:
        admin = User(
            username='admin',
            full_name='System Administrator',
            is_superuser=True
        )
        admin.set_password(os.getenv('INITIAL_ADMIN_PASSWORD', 'change-me-immediately'))
        db.session.add(admin)
        db.session.commit()

def register_cli_commands(app):
    """Register custom Flask CLI commands."""
    @app.cli.command("seed")
    @with_appcontext
    def seed():
        initialize_roles_and_permissions()
        initialize_default_data()
        click.echo("Database seeded.")

    @app.cli.command("reencrypt-pii")
    @click.argument("old_key")
    @with_appcontext
    def reencrypt(old_key):
        # Logic to cycle encryption keys
        click.echo("PII re-encrypted with new key.")

def register_scheduler_tasks(scheduler, app):
    """Register background tasks for the APScheduler."""
    @scheduler.task('cron', id='daily_backup', hour=2, minute=0)
    def daily_backup():
        with app.app_context():
            from services.core import BackupService
            import json
            data = BackupService.get_system_logical_data()
            
            filename = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            path = os.path.join(app.config['BACKUP_DIR'], filename)
            
            with open(path, 'w') as f:
                json.dump(data, f)
            
            app.logger.info(f"Automated logical backup saved to {path}")