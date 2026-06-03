import unittest
from app import create_app
import os
from models import db, User, Customer, Device, Ticket

class BasicTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('testing')
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()
        db.create_all()

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
        user = User.query.filter_by(username='admin').first()
        self.assertIsNotNone(user)
        self.assertTrue(user.is_superuser)

    def test_customer_creation(self):
        """Test manual customer record addition"""
        c = Customer(name="Test User", phone="123456789")
        db.session.add(c)
        db.session.commit()
        self.assertEqual(Customer.query.count(), 1)

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
        admin_password = os.getenv('INITIAL_ADMIN_PASSWORD', 'change-me-immediately')
        # Admin is created by default in app initialization context
        response = self.client.post('/auth/login', data=dict(
            username='admin',
            password=admin_password
        ), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Logged in successfully', response.data)

if __name__ == "__main__":
    unittest.main()