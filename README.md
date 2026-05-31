# Repair Shop Ticketing Web App

A complete Python Flask web application for managing repair shop tickets with a local SQLite database.

## Features

- 👤 User Authentication & Authorization
- 🎟️ Repair Ticket Management (Create, Read, Update)
- 👥 Customer Management
- 👨‍🔧 Technician Assignment
- 📝 Notes & Updates Tracking
- 📊 Dashboard with Statistics
- 🏷️ Priority & Status Management
- 💰 Cost Tracking (Estimated & Actual)
- 📱 Responsive UI with Bootstrap

## Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Git (optional)

## Installation

### 1. Clone Repository
```bash
git clone https://github.com/ndarjo/repair-shop-REDACTED_PASSWORD.git
cd repair-shop-REDACTED_PASSWORD
```

### 2. Create Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run Application
```bash
python app.py
```

The application will be available at `http://localhost:5000`

## First Time Setup

1. Register a new account as admin/technician
2. Create customers in the system
3. Create repair tickets for customers
4. Track ticket status and add notes

## Project Structure

```
repair-shop-REDACTED_PASSWORD/
├── app.py                 # Main Flask application
├── models.py             # Database models
├── routes.py             # Route handlers
├── config.py             # Configuration settings
├── requirements.txt      # Python dependencies
├── templates/            # HTML templates
│   ├── base.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── new_ticket.html
│   ├── ticket_detail.html
│   ├── edit_ticket.html
│   ├── new_customer.html
│   └── customers.html
└── static/               # Static files
    ├── css/
    │   └── style.css
    └── js/
        └── main.js
```

## Database Models

### User
- Username, Email, Password
- Full Name, Role (admin/technician/manager)
- Timestamps

### Customer
- First Name, Last Name
- Phone, Email, Address
- City, Zip Code
- Timestamps

### Ticket
- Ticket Number (auto-generated)
- Customer Reference
- Device Information (Type, Brand, Model, Serial)
- Issue Description
- Status (Open, In Progress, Waiting for Parts, On Hold, Completed, Cancelled)
- Priority (Low, Medium, High, Urgent)
- Estimated & Actual Costs
- Assigned Technician
- Timestamps

### Note
- Ticket Reference
- Author (User)
- Content
- Timestamp

## Usage

### Creating a Ticket
1. Click "New Ticket" button
2. Select or create a customer
3. Enter device information
4. Describe the issue
5. Set priority and assign technician
6. Submit

### Updating a Ticket
1. Go to Dashboard
2. Click "View" on any ticket
3. Click "Edit" button
4. Update status, priority, costs, or assignment
5. Save changes

### Adding Notes
1. Open ticket detail
2. Scroll to "Notes & Updates" section
3. Add your note
4. Submit

## Configuration

Edit `config.py` to change:
- Database URI
- Secret Key
- Debug Mode
- Session settings

## Deployment

For production deployment:

1. Change `SECRET_KEY` in config.py
2. Set `DEBUG = False`
3. Use PostgreSQL instead of SQLite
4. Deploy to Heroku, AWS, or similar platform

## Support

For issues or questions, please create an issue on GitHub.

## License

MIT License - feel free to use this project for your repair shop!
