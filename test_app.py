import unittest
import os
from decimal import Decimal
from sqlalchemy import func
from flask import url_for
from flask_login import login_user
from app import create_app
from models import db, User, Customer, Device, Ticket, Location, Note, ShopSetting, Permission, Role, SparePart, Service, Invoice
from services.ticket import RepairTicketService
from services.core import InventoryService

class BasicTests(unittest.TestCase):
    def setUp(self):
        """Set up a fresh testing environment for every test case"""
        self.app = create_app('testing')
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

        # Admin credentials from environment or defaults (matches services/setup.py)
        self.admin_username = os.getenv('INITIAL_ADMIN_USERNAME') or 'admin'
        self.admin_password = os.getenv('INITIAL_ADMIN_PASSWORD') or 'change-me-immediately'
        if len(self.admin_password) < 8:
            self.admin_password = 'change-me-immediately'

        # INTEGRITY: Ensure a ShopSetting exists to mark setup as completed 
        # This prevents the check_onboarding middleware from redirecting tests.
        setting = db.session.scalar(db.select(ShopSetting))
        if not setting:
            loc = db.session.scalar(db.select(Location))
            setting = ShopSetting(
                location_id=loc.id if loc else 1, 
                shop_name="Production Test Shop", 
                setup_completed=True
            )
            db.session.add(setting)
        setting.setup_completed = True
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_main_page_redirect(self):
        """Check that unauthenticated users are redirected to login"""
        # UX Consistency: Verify standardized unauthorized redirection
        response = self.client.get('/', follow_redirects=True)
        self.assertIn(b'Please log in to access this page', response.data)

    def test_superuser_creation(self):
        """Verify that the superuser is automatically initialized with correct attributes"""
        user = db.session.scalar(db.select(User).where(func.lower(User.username) == func.lower(self.admin_username)))
        self.assertIsNotNone(user)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_active)

    def test_customer_creation(self):
        """Test manual customer record addition"""
        # Integrity: Customer must be associated with a location in multi-tenant environments
        loc = db.session.scalar(db.select(Location))
        c = Customer(name="Test User", phone="123456789", location_id=loc.id)
        db.session.add(c)
        db.session.commit()
        self.assertEqual(db.session.scalar(db.select(func.count(Customer.id))), 1)

    def test_customer_encryption_consistency(self):
        """Verify that customer PII can be decrypted with the current key"""
        test_phone = "+1 (555) 000-9999"
        loc = db.session.scalar(db.select(Location))
        c = Customer(name="Crypto Test", phone=test_phone, location_id=loc.id)
        db.session.add(c)
        db.session.commit()
        
        # Fetch from DB to trigger decryption logic in the model
        db.session.expire_all()
        fetched = db.session.get(Customer, c.id)
        self.assertEqual(fetched.phone, test_phone)

    def test_customer_search_hash(self):
        """Ensure blind indexing for PII works for searching without decryption"""
        test_phone = "987654321"
        loc = db.session.scalar(db.select(Location))
        c = Customer(name="Search Test", phone=test_phone, location_id=loc.id)
        db.session.add(c)
        db.session.commit()
        
        # Integrity: Test exact match via the HMAC blind index
        h = Customer.get_search_hash(test_phone)
        found = db.session.scalar(db.select(Customer).filter_by(phone_hash=h))
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "Search Test")

    def test_customer_anonymization(self):
        """Verify GDPR 'Right to be Forgotten' logic"""
        loc = db.session.scalar(db.select(Location))
        c = Customer(name="Delete Me", phone="123", address="Secret St", location_id=loc.id)
        db.session.add(c)
        db.session.commit()
        
        customer_id = c.id
        c.anonymize()
        db.session.commit()
        
        # Integrity: Check that data is scrubbed but record persists for audit logs
        fetched = db.session.get(Customer, customer_id)
        self.assertIn("DELETED_USER", fetched.name)
        self.assertEqual(fetched.phone, "0000000000")
        self.assertEqual(fetched.address, "ANONYMIZED")
        
        # Security: Blind index must be updated to the new value to prevent leaks
        new_hash = Customer.get_search_hash("0000000000")
        self.assertEqual(fetched.phone_hash, new_hash)

    def test_ticket_number_generation(self):
        """Ensure ticket numbers are unique and formatted correctly"""
        num1 = Ticket.generate_unique_number()
        num2 = Ticket.generate_unique_number()
        self.assertNotEqual(num1, num2)
        self.assertTrue(num1.startswith('TKT-'))

    def test_login_logic(self):
        """Verify authentication flow"""
        # Admin is created by default in app initialization context
        response = self.client.post('/Auth/login', data=dict(
            username=self.admin_username,
            password=self.admin_password
        ), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Logged in successfully', response.data)

    def test_location_scoping_integrity(self):
        """Verify that records are logically separated by location_id for multi-tenancy"""
        # Create fresh branches to verify isolation
        loc1 = Location(name="Branch North")
        loc2 = Location(name="Branch South")
        db.session.add_all([loc1, loc2])
        db.session.flush()
        
        cust_a = Customer(name="North Client", phone="111", location_id=loc1.id)
        cust_b = Customer(name="South Client", phone="222", location_id=loc2.id)
        db.session.add_all([cust_a, cust_b])
        db.session.commit()
        
        # Verify that a query scoped to Location 1 does not leak Location 2 data
        results = db.session.scalars(db.select(Customer).filter_by(location_id=loc1.id)).all()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "North Client")

    def test_permission_active_user_check(self):
        """Security: Verify that deactivated users lose all permissions immediately"""
        admin = db.session.scalar(db.select(User).filter_by(is_superuser=True))
        self.assertTrue(admin.has_permission('view_reports'))
        
        # Deactivate user
        admin.is_active = False
        db.session.commit()
        
        # Check Permission Integrity
        self.assertFalse(admin.has_permission('view_reports'))
        self.assertFalse(admin.has_role('admin'))

        # Check Auth UX
        response = self.client.post('/Auth/login', data=dict(
            username=self.admin_username,
            password=self.admin_password
        ), follow_redirects=True)
        self.assertIn(b'Your account is inactive', response.data or b'')

    def test_ticket_timeline_aggregation(self):
        """Verify the Ticket.timeline property merges phase logs and notes correctly"""
        loc = db.session.scalar(db.select(Location))
        cust = Customer(name="Timeline Test", phone="555", location_id=loc.id)
        dev = Device(customer=cust, device_type="Phone", brand="TestBrand")
        db.session.add_all([cust, dev])
        db.session.flush()

        admin = db.session.scalar(db.select(User).where(func.lower(User.username) == func.lower(self.admin_username)))
        # Use the service to ensure initial phase logs are created
        ticket = RepairTicketService.create_ticket(
            customer_id=cust.id, device_id=dev.id, location_id=loc.id,
            creator_id=admin.id, items_included="None", problem_description="Broken Screen"
        )
        
        # Add a manual note
        note = Note(ticket=ticket, user_id=admin.id, content="Started diagnostic", note_type="Technical")
        db.session.add(note)
        db.session.commit()
        
        # Timeline should have 2 events: 1 Phase Log (Open) and 1 Note
        self.assertEqual(len(ticket.timeline), 2)
        event_types = [e['type'] for e in ticket.timeline]
        self.assertIn('phase', event_types)
        self.assertIn('note', event_types)

    def test_inventory_and_services_views(self):
        """Verify that the inventory and services templates render correctly for admin"""
        self.client.post('/Auth/login', data=dict(
            username=self.admin_username,
            password=self.admin_password
        ), follow_redirects=True)
        
        with self.app.test_request_context():
            inv_url = url_for('inventory.manage_inventory')
            srv_url = url_for('services.manage_services')

        # Access inventory with URL integrity
        response = self.client.get(inv_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Spare Parts', response.data)
        
        # Access services with URL integrity
        response = self.client.get(srv_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Service Types', response.data)

    def test_financial_and_inventory_integrity(self):
        """Verify cross-service integrity: Ticket creation -> Stock decrement -> Financial balancing"""
        loc = db.session.scalar(db.select(Location))
        admin = db.session.scalar(db.select(User).filter_by(is_superuser=True))
        
        # 1. Setup Data
        part = SparePart(name="OLED Screen", selling_price=Decimal('120.00'), stock_quantity=10, location_id=loc.id)
        service = Service(name="Screen Fitting", price=Decimal('40.00'), location_id=loc.id)
        cust = Customer(name="Integrity Test", phone="999", location_id=loc.id)
        dev = Device(customer=cust, device_type="Phone", brand="Apple")
        db.session.add_all([part, service, cust, dev])
        db.session.flush()
        
        # 2. Create Ticket with Down Payment
        ticket = RepairTicketService.create_ticket(
            customer_id=cust.id, device_id=dev.id, location_id=loc.id,
            creator_id=admin.id, items_included="Phone only", problem_description="Broken Screen",
            down_payment=Decimal('50.00'), payment_method='Card'
        )
        
        # 3. Add Items via Service (requiring auth context for current_user access)
        with self.app.test_request_context():
            login_user(admin)
            InventoryService.add_part_to_ticket(ticket.id, part.id, None, 1, None, None)
            InventoryService.add_service_to_ticket(ticket.id, service.id, 1)
        
        db.session.refresh(ticket)
        db.session.refresh(part)
        
        # Integrity Checks
        self.assertEqual(part.stock_quantity, 9) # Stock correctly decremented
        self.assertEqual(ticket.grand_total, Decimal('160.00')) # 120 (part) + 40 (service)
        self.assertEqual(ticket.total_paid, Decimal('50.00')) # Initial down payment tracked
        self.assertEqual(ticket.balance_due, Decimal('110.00')) # 160 - 50 = 110
        
        invoice = db.session.scalar(db.select(Invoice).filter_by(ticket_id=ticket.id))
        self.assertEqual(invoice.status, 'Partial')

    def test_ajax_error_responses_integrity(self):
        """UX Consistency: Verify that error handlers return JSON for AJAX/API requests"""
        # 1. Unauthorized AJAX (401)
        response = self.client.get('/customer/list', headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.is_json)
        self.assertIn('Unauthorized', response.json['error'])

        # 2. Not Found AJAX (404)
        response = self.client.get('/api/missing_endpoint', headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(response.status_code, 404)
        self.assertTrue(response.is_json)
        self.assertEqual(response.json['error'], 'Not Found')

    def test_decryption_error_handler(self):
        """Security/Integrity: Verify handling of PII decryption failures"""
        from cryptography.fernet import InvalidToken

        # Simulate a decryption failure inside a request context
        @self.app.route('/test-decrypt-error')
        def trigger_error():
            raise InvalidToken()

        response = self.client.get('/test-decrypt-error', follow_redirects=True)
        # Should redirect to dashboard with a flash message
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Security Error', response.data)
        self.assertIn(b'Unable to decrypt', response.data)

if __name__ == "__main__":
    unittest.main()