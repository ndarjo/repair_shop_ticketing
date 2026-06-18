import os
import json
import subprocess
from datetime import datetime
from typing import Dict, Any, Tuple
from flask import current_app # type: ignore
from models import db, Location, Customer, Device, Ticket, ShopSetting, User, SparePart, Service, Payment, Invoice, InvoiceItem, Note, PhaseLog, TicketService, Role, Permission, CommonProblem
from sqlalchemy import text
from sqlalchemy.orm import joinedload
from sqlalchemy.engine import make_url
from flask_babel import _

class BackupService:
    @staticmethod
    def get_system_logical_data() -> Dict[str, Any]:
        """Prepares a dictionary of all critical system data for export"""
        return {
            'users': [{
                'id': u.id, 'username': u.username, 'password_hash': u.password_hash,
                'full_name': u.full_name, 'email': u.email, 'is_active': u.is_active,
                'is_superuser': u.is_superuser, 'location_id': u.location_id,
                'language_preference': u.language_preference, 'theme_preference': u.theme_preference,
                'color_theme': u.color_theme, 'currency': u.currency,
                'currency_decimals': u.currency_decimals,
                'roles': [r.name for r in u.roles]
            } for u in db.session.execute(db.select(User).options(joinedload(User.roles))).scalars().unique().all()],
            'roles': [{
                'id': r.id, 'name': r.name,
                'permissions': [p.name for p in r.permissions] # Export permission names linked to role
            } for r in db.session.execute(db.select(Role).options(joinedload(Role.permissions))).scalars().unique().all()],
            'permissions': [{
                'id': p.id, 'name': p.name, 'category': p.category
            } for p in db.session.execute(db.select(Permission)).scalars().all()],
            'locations': [{
                'id': l.id, 'name': l.name, 'address': l.address, 
                'phone': l.phone, 'email': l.email,
                'created_at': l.created_at.isoformat() if l.created_at else None
            } for l in db.session.execute(db.select(Location)).scalars().all()],
            'customers': [{
                'id': c.id, 'name': c.name, 'phone': c.phone, 'phone_hash': c.phone_hash,
                'address': c.address, 'location_id': c.location_id,
                'created_at': c.created_at.isoformat() if c.created_at else None
            } for c in db.session.execute(db.select(Customer)).scalars().all()],
            'devices': [{
                'id': d.id, 'customer_id': d.customer_id, 'device_type': d.device_type, 
                'brand': d.brand, 'model_number': d.model_number, 'serial_number': d.serial_number,
                'color': d.color, 'cpu': d.cpu, 'ram': d.ram, 'storage_type': d.storage_type,
                'storage_capacity': d.storage_capacity, 'notes': d.notes,
                'created_at': d.created_at.isoformat() if d.created_at else None
            } for d in db.session.execute(db.select(Device)).scalars().all()],
            'tickets': [{
                'id': t.id, 'ticket_number': t.ticket_number, 'customer_id': t.customer_id,
                'device_id': t.device_id, 'location_id': t.location_id, 'creator_id': t.creator_id,
                'assigned_to': t.assigned_to, 'items_included': t.items_included,
                'problem_description': t.problem_description,
                'current_phase': t.current_phase, 'actual_cost': str(t.actual_cost) if t.actual_cost is not None else None,
                'created_at': t.created_at.isoformat() if t.created_at else None,
                'is_archived': t.is_archived, 'down_payment': str(t.down_payment) if t.down_payment is not None else None,
                'payment_method': t.payment_method, 'device_picked_up': t.device_picked_up,
                'picked_up_date': t.picked_up_date.isoformat() if t.picked_up_date else None
            } for t in db.session.execute(db.select(Ticket)).scalars().all()],
            'ticket_services': [{
                'id': ts.id, 'ticket_id': ts.ticket_id, 'service_id': ts.service_id,
                'quantity': ts.quantity, 'price_charged': str(ts.price_charged) if ts.price_charged is not None else '0.00'
            } for ts in db.session.execute(db.select(TicketService)).scalars().all()],
            'services': [{
                'id': s.id, 'name': s.name, 'description': s.description,
                'price': str(s.price) if s.price is not None else '0.00', 'location_id': s.location_id, 'is_active': s.is_active
            } for s in db.session.execute(db.select(Service)).scalars().all()],
            'parts': [{
                'id': p.id, 'sku': p.sku, 'name': p.name,
                'cost': str(p.cost) if p.cost is not None else None, 'selling_price': str(p.selling_price) if p.selling_price is not None else '0.00',
                'stock_quantity': p.stock_quantity, 'location_id': p.location_id, 'is_active': p.is_active
            } for p in db.session.execute(db.select(SparePart)).scalars().all()],
            'invoices': [{
                'id': i.id, 'invoice_number': i.invoice_number, 'ticket_id': i.ticket_id,
                'customer_id': i.customer_id, 'location_id': i.location_id,
                'status': i.status, 'total_amount': str(i.total_amount) if i.total_amount is not None else '0.00',
                'created_at': i.created_at.isoformat() if i.created_at else None
            } for i in db.session.execute(db.select(Invoice)).scalars().all()],
            'invoice_items': [{
                'id': ii.id, 'invoice_id': ii.invoice_id, 'description': ii.description,
                'spare_part_id': ii.spare_part_id, 'quantity': ii.quantity,
                'cost_price': str(ii.cost_price) if ii.cost_price is not None else '0.00',
                'unit_price': str(ii.unit_price) if ii.unit_price is not None else '0.00',
                'total_price': str(ii.total_price) if ii.total_price is not None else '0.00'
            } for ii in db.session.execute(db.select(InvoiceItem)).scalars().all()],
            'payments': [{
                'id': p.id, 'ticket_id': p.ticket_id, 'invoice_id': p.invoice_id,
                'user_id': p.user_id, 'amount': str(p.amount) if p.amount is not None else '0.00',
                'payment_method': p.payment_method, 'transaction_reference': p.transaction_reference,
                'paid_at': p.paid_at.isoformat() if p.paid_at else None
            } for p in db.session.execute(db.select(Payment)).scalars().all()],
            'notes': [{
                'id': n.id, 'ticket_id': n.ticket_id, 'user_id': n.user_id, 'note_type': n.note_type,
                'content': n.content, 'is_internal': n.is_internal, 'created_at': n.created_at.isoformat() if n.created_at else None
            } for n in db.session.execute(db.select(Note)).scalars().all()],
            'phase_logs': [{
                'id': pl.id, 'ticket_id': pl.ticket_id, 'user_id': pl.user_id, 'old_phase': pl.old_phase,
                'new_phase': pl.new_phase, 'changed_at': pl.changed_at.isoformat() if pl.changed_at else None
            } for pl in db.session.execute(db.select(PhaseLog)).scalars().all()],
            'shop_settings': [{
                'shop_name': s.shop_name, 'shop_address': s.shop_address,
                'shop_phone': s.shop_phone, 'shop_email': s.shop_email,
                'location_id': s.location_id, 'logo_path': s.logo_path,
                'setup_completed': s.setup_completed
            } for s in db.session.execute(db.select(ShopSetting)).scalars().all()],
            'common_problems': [{
                'id': cp.id, 'problem_text': cp.problem_text, 
                'location_id': cp.location_id, 'is_active': cp.is_active
            } for cp in db.session.execute(db.select(CommonProblem)).scalars().all()]
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
                url_obj = make_url(db_url)
                env = os.environ.copy()
                if url_obj.password:
                    env['PGPASSWORD'] = url_obj.password
                
                cmd = ['pg_dump', '-Fc', '-f', dump_path]
                if url_obj.host: cmd.extend(['-h', url_obj.host])
                if url_obj.port: cmd.extend(['-p', str(url_obj.port)])
                if url_obj.username: cmd.extend(['-U', url_obj.username])
                cmd.append(url_obj.database)

                subprocess.run(cmd, env=env, check=True, capture_output=True)
                snapshot_success = True
            except Exception as e:
                current_app.logger.error(f"Automated full dump failed: {str(e)}")

        # 2. Logical Data Backup (Always performed as fallback/supplement)
        try:
            data = BackupService.get_system_logical_data()
            json_name = f"autobackup_logical_{now_str}.json"
            json_path = os.path.join(backup_dir, json_name)
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            msg = _("Automated backup completed. Logical: %(json)s", json=json_name)
            if snapshot_success:
                msg += _(", Full: %(dump)s", dump=dump_name)
            return True, msg
        except Exception as e:
            current_app.logger.error(f"Automated logical backup failed: {str(e)}")
            return False, _("Logical backup failed: %(error)s", error=str(e))

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

            # 1. Release active connections (except this one) to prevent locks
            db.session.execute(text("""
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = :db_name AND pid <> pg_backend_pid();
            """), {"db_name": db_name})
            db.session.commit()

            # 2. Run pg_restore
            # --clean: Drop database objects before recreating them
            # --if-exists: Use IF EXISTS when dropping objects
            # --no-owner: Do not set ownership of objects to match the original database
            env = os.environ.copy()
            if url.password:
                env['PGPASSWORD'] = url.password

            cmd = ['pg_restore', '--clean', '--if-exists', '--no-owner', '-d', url.database]
            if url.host: cmd.extend(['-h', url.host])
            if url.port: cmd.extend(['-p', str(url.port)])
            if url.username: cmd.extend(['-U', url.username])
            cmd.append(file_path)
            
            subprocess.run(cmd, env=env, check=True, capture_output=True)
            return True, _("Success")

        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode() if e.stderr else "pg_restore failed"
            current_app.logger.error(f"Restore failed: {err_msg}")
            return False, _("Restore failed: %(msg)s", msg=err_msg)
        except Exception as e:
            current_app.logger.error(f"Unexpected restore error: {str(e)}")
            return False, _("Unexpected restore error: %(error)s", error=str(e))
