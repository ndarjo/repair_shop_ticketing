import unittest
from app import create_app
import os
from sqlalchemy import func
from models import db, User, Customer, Device, Ticket, Location, Note, ShopSetting

class BasicTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

        # Seed ShopSetting to mark setup as completed so tests don't redirect to onboarding
        loc = db.session.scalar(db.select(Location))
        setting = db.session.scalar(db.select(ShopSetting))
        if not setting:
            setting = ShopSetting(
                location_id=loc.id if loc else 1, 
                shop_name="Test Shop", 
                setup_completed=True
            )
            db.session.add(setting)
        else:
            setting.setup_completed = True
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_main_page_redirect(self):
        """Check that unauthenticated users are redirected to login"""
        response = self.client.get('/', follow_redirects=True)
        self.assertIn(b'Please log in to access this page', response.data)

    def test_superuser_creation(self):
        """Verify that the superuser initialization works"""
        admin_username = os.getenv('INITIAL_ADMIN_USERNAME') or 'admin'
        user = db.session.scalar(db.select(User).where(func.lower(User.username) == func.lower(admin_username)))
        self.assertIsNotNone(user)
        self.assertTrue(user.is_superuser)

    def test_customer_creation(self):
        """Test manual customer record addition"""
        c = Customer(name="Test User", phone="123456789")
        db.session.add(c)
        db.session.commit()
        self.assertEqual(db.session.scalar(db.select(func.count(Customer.id))), 1)

    def test_customer_encryption_consistency(self):
        """Verify that customer PII can be decrypted with the current key"""
        test_phone = "+1 (555) 000-9999"
        c = Customer(name="Crypto Test", phone=test_phone)
        db.session.add(c)
        db.session.commit()
        
        # Fetch from DB to trigger decryption logic in the model
        db.session.expire_all()
        fetched = db.session.get(Customer, c.id)
        self.assertEqual(fetched.phone, test_phone)

    def test_ticket_number_generation(self):
        """Ensure ticket numbers are unique and formatted correctly"""
        num1 = Ticket.generate_unique_number()
        num2 = Ticket.generate_unique_number()
        self.assertNotEqual(num1, num2)
        self.assertTrue(num1.startswith('TKT-'))

    def test_login_logic(self):
        """Verify authentication flow"""
        admin_username = os.getenv('INITIAL_ADMIN_USERNAME') or 'admin'
        admin_password = os.getenv('INITIAL_ADMIN_PASSWORD') or 'change-me-immediately'
        if len(admin_password) < 8:
            admin_password = 'change-me-immediately'
        # Admin is created by default in app initialization context
        response = self.client.post('/auth/login', data=dict(
            username=admin_username,
            password=admin_password
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

    def test_ticket_timeline_aggregation(self):
        """Verify the Ticket.timeline property merges phase logs and notes correctly"""
        from services.ticket import RepairTicketService
        
        loc = db.session.scalar(db.select(Location))
        cust = Customer(name="Timeline Test", phone="555", location_id=loc.id)
        dev = Device(customer=cust, device_type="Phone", brand="TestBrand")
        db.session.add_all([cust, dev])
        db.session.flush()
        
        admin_username = os.getenv('INITIAL_ADMIN_USERNAME') or 'admin'
        admin = db.session.scalar(db.select(User).where(func.lower(User.username) == func.lower(admin_username)))
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
        admin_username = os.getenv('INITIAL_ADMIN_USERNAME') or 'admin'
        admin_password = os.getenv('INITIAL_ADMIN_PASSWORD') or 'change-me-immediately'
        if len(admin_password) < 8:
            admin_password = 'change-me-immediately'
        self.client.post('/auth/login', data=dict(
            username=admin_username,
            password=admin_password
        ), follow_redirects=True)
        
        # Access inventory
        response = self.client.get('/inventory')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Spare Parts', response.data)
        
        # Access services
        response = self.client.get('/services')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Service Types', response.data)

if __name__ == "__main__":
    unittest.main()