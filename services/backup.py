from typing import Dict, Any
from models import Location, Customer, Device, Ticket, ShopSetting

class BackupService:
    @staticmethod
    def get_system_logical_data() -> Dict[str, Any]:
        """Prepares a dictionary of all critical system data for export"""
        return {
            'locations': [{
                'id': l.id, 'name': l.name, 'address': l.address,
                'created_at': l.created_at.isoformat() if l.created_at else None
            } for l in Location.query.all()],
            'customers': [{
                'id': c.id, 'name': c.name, 'phone': c.phone, 'address': c.address, 
                'created_at': c.created_at.isoformat() if c.created_at else None
            } for c in Customer.query.all()],
            'devices': [{
                'id': d.id, 'customer_id': d.customer_id, 'device_type': d.device_type, 
                'brand': d.brand, 'model_number': d.model_number, 'serial_number': d.serial_number,
                'created_at': d.created_at.isoformat() if d.created_at else None
            } for d in Device.query.all()],
            'tickets': [{
                'id': t.id, 'ticket_number': t.ticket_number, 'customer_id': t.customer_id, 
                'current_phase': t.current_phase, 'estimated_cost': str(t.estimated_cost),
                'actual_cost': str(t.actual_cost), 'created_at': t.created_at.isoformat() if t.created_at else None
            } for t in Ticket.query.all()],
            'shop_settings': [{
                'shop_name': s.shop_name, 'shop_address': s.shop_address,
                'shop_phone': s.shop_phone, 'shop_email': s.shop_email,
                'setup_completed': s.setup_completed
            } for s in ShopSetting.query.all()]
        }
