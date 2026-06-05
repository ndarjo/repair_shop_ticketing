import os
import json
import subprocess
from datetime import datetime
from typing import Dict, Any, Tuple
from flask import current_app
from models import db, Location, Customer, Device, Ticket, ShopSetting
from sqlalchemy import text
from sqlalchemy.engine import make_url

class BackupService:
    @staticmethod
    def get_system_logical_data() -> Dict[str, Any]:
        """Prepares a dictionary of all critical system data for export"""
        return {
            'locations': [{
                'id': l.id, 'name': l.name, 'address': l.address,
                'created_at': l.created_at.isoformat() if l.created_at else None
            } for l in db.session.execute(db.select(Location)).scalars().all()],
            'customers': [{
                'id': c.id, 'name': c.name, 'phone': c.phone, 'address': c.address, 
                'created_at': c.created_at.isoformat() if c.created_at else None
            } for c in db.session.execute(db.select(Customer)).scalars().all()],
            'devices': [{
                'id': d.id, 'customer_id': d.customer_id, 'device_type': d.device_type, 
                'brand': d.brand, 'model_number': d.model_number, 'serial_number': d.serial_number,
                'created_at': d.created_at.isoformat() if d.created_at else None
            } for d in db.session.execute(db.select(Device)).scalars().all()],
            'tickets': [{
                'id': t.id, 'ticket_number': t.ticket_number, 'customer_id': t.customer_id, 
                'current_phase': t.current_phase, 'estimated_cost': str(t.estimated_cost),
                'actual_cost': str(t.actual_cost), 'created_at': t.created_at.isoformat() if t.created_at else None
            } for t in db.session.execute(db.select(Ticket)).scalars().all()],
            'shop_settings': [{
                'shop_name': s.shop_name, 'shop_address': s.shop_address,
                'shop_phone': s.shop_phone, 'shop_email': s.shop_email,
                'setup_completed': s.setup_completed
            } for s in db.session.execute(db.select(ShopSetting)).scalars().all()]
        }

    @staticmethod
    def run_automated_backup() -> Tuple[bool, str]:
        """
        Performs both a full binary dump (if PostgreSQL) and a logical JSON export.
        Used by the scheduler.
        """
        now_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = current_app.config['BACKUP_DIR']
        
        # 1. Full Database Snapshot
        db_url = current_app.config['SQLALCHEMY_DATABASE_URI']
        dump_name = f"autobackup_full_{now_str}.dump"
        dump_path = os.path.join(backup_dir, dump_name)
        
        snapshot_success = False
        if 'postgresql' in db_url:
            try:
                # Clean URI: strip driver from postgresql+psycopg://...
                clean_url = db_url.replace('+psycopg', '')
                subprocess.run(['pg_dump', '--dbname', clean_url, '-Fc', '-f', dump_path], check=True, capture_output=True)
                snapshot_success = True
            except Exception as e:
                current_app.logger.error(f"Automated full dump failed: {str(e)}")

        # 2. Logical Data Backup (Always performed as fallback/supplement)
        try:
            data = BackupService.get_system_logical_data()
            json_name = f"autobackup_logical_{now_str}.json"
            json_path = os.path.join(backup_dir, json_name)
            with open(json_path, 'w') as f:
                json.dump(data, f)
            
            msg = f"Automated backup completed. Logical: {json_name}"
            if snapshot_success:
                msg += f", Full: {dump_name}"
            return True, msg
        except Exception as e:
            current_app.logger.error(f"Automated logical backup failed: {str(e)}")
            return False, str(e)

    @staticmethod
    def restore_full_backup(file_path: str) -> Tuple[bool, str]:
        """
        Restores a PostgreSQL binary dump using pg_restore.
        Releases active database connections to prevent hanging.
        """
        db_url = current_app.config['SQLALCHEMY_DATABASE_URI']
        if 'postgresql' not in db_url:
            return False, _('Restore is only supported for PostgreSQL.')

        try:
            url = make_url(db_url)
            db_name = url.database
            # System tools require raw postgresql:// syntax
            clean_url = db_url.replace('+psycopg', '')

            # 1. Release active connections (except this one) to prevent locks
            # We use a raw connection to ensure the command is sent directly
            db.session.execute(text(f"""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = '{db_name}' AND pid <> pg_backend_pid();
            """))
            db.session.commit()

            # 2. Run pg_restore
            # --clean: Drop database objects before recreating them
            # --if-exists: Use IF EXISTS when dropping objects
            # --no-owner: Do not set ownership of objects to match the original database
            cmd = ['pg_restore', '--dbname', clean_url, '--clean', '--if-exists', '--no-owner', file_path]
            
            subprocess.run(cmd, check=True, capture_output=True)
            return True, "Success"

        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode() if e.stderr else "pg_restore failed"
            current_app.logger.error(f"Restore failed: {err_msg}")
            return False, f"Restore failed: {err_msg}"
        except Exception as e:
            current_app.logger.error(f"Unexpected restore error: {str(e)}")
            return False, str(e)
