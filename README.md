# Repair Shop Ticketing System

A comprehensive Python Flask web application for managing repair shop operations with advanced features including ticket management, invoicing, service pricing, device tracking, and multi-theme support.

## ✨ Features

### Core Features
- 👤 **User Authentication & Authorization** with role-based access control
- 🎟️ **Repair Ticket Management** (Create, Read, Update, Phase Tracking)
- 👥 **Customer Management** with contact information
- 📱 **Device Tracking** - Track multiple devices per customer
- 👨‍🔧 **Technician Assignment** to tickets
- 📝 **Notes & Updates** tracking with timestamps
- 📊 **Dashboard** with comprehensive statistics
- 🔄 **Phase Management** - Open, Diagnostic, Waiting for Parts, Repairing, Finished, Cancelled

### Advanced Features
- 💰 **Service Pricing** - Add and manage repair services with prices
- 🔧 **Spare Parts Management** - Track replaced hardware and parts
- 📄 **Invoice Generation** - Auto-generate professional PDF invoices
- 💳 **Payment Tracking** - Down payments, full payments, and partial payments
- 🛠️ **Common Problems** - Customizable quick-select problem descriptions
- 📋 **Reports & Analytics** - Monthly statistics and revenue tracking
- 📦 **System Backups** - Full SQLite database and JSON logical exports
- 🌙 **Dark/Light Theme** - User preference for light and dark modes
- 🎨 **Color Themes** - Multiple color schemes (Blue, Green, Purple, Red, Orange)
- ⏰ **24-Hour Time Format** - Professional time display (no AM/PM)
- 🔐 **Permission-Based Access** - Granular permissions grouped by category

## 📋 Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Git (optional)

## 🚀 Installation

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

## 🔑 Default Credentials

After first run, you'll have a default superuser account:
- **Username:** admin
- **Password:** REDACTED_PASSWORD

⚠️ **Important:** Change the password immediately in production!

## 📁 Project Structure

```
repair-shop-REDACTED_PASSWORD/
├── app.py                      # Main Flask application & initialization
├── models.py                   # Database models & schema
├── routes.py                   # Route handlers & business logic
├── config.py                   # Configuration settings
├── requirements.txt            # Python dependencies
├── README.md                   # This file
├── templates/                  # HTML templates
│   ├── base.html              # Base template with navigation
│   ├── login.html             # Login page
│   ├── profile.html           # User profile & theme settings
│   ├── dashboard.html         # Main dashboard
│   ├── tickets_list.html      # Full repair ticket directory
│   ├── ticket_form.html       # Ticket intake form with AJAX search
│   ├── ticket_detail.html     # View ticket details
│   ├── edit_ticket.html       # Edit repair details and assignment
│   ├── new_customer.html      # Create new customer
│   ├── customer_detail.html   # View customer details
│   ├── customers.html         # Customer list
│   ├── devices.html           # Dedicated devices tab
│   ├── new_device.html        # Add device for customer
│   ├── edit_device.html       # Edit device details
│   ├── invoice.html           # View invoice
│   ├── reports.html           # Reports & analytics
│   ├── admin/
│   │   ├── dashboard.html     # Admin dashboard
│   │   ├── manage_users.html  # User management
│   │   ├── create_user.html   # Create new user
│   │   ├── edit_user.html     # Edit user with permission grid
│   │   ├── manage_common_problems.html  # Common problems management
│   │   └── backup.html        # Backup & restore page
│   └── ...
└── static/                     # Static files
    ├── css/
    │   └── style.css          # Main stylesheet
    └── js/
        └── main.js            # Client-side scripts
```

## 🗄️ Database Models

### User
- Username (unique), Email (optional)
- Full Name, Password Hash
- Superuser flag, Active status
- Theme preference (light/dark), Color theme
- Roles & Permissions (many-to-many)
- Creation timestamp

### Role
- Role name (admin, technician, receptionist, manager)
- Description
- Associated users (many-to-many)

### Permission
- Permission name (e.g., create_ticket, view_customer)
- Description, Category (tickets, customers, payments, users, reports)
- Associated users (many-to-many)

### Customer
- Name (required), Phone (required)
- Address (optional)
- Multiple devices relationship
- Creation & update timestamps

### Device
- Device type (Phone, Laptop, Tablet, etc.)
- Brand, Model, Model number
- CPU, RAM, Storage type & capacity
- Serial number, Color
- Notes
- Customer reference
- Multiple tickets relationship

### Ticket
- Ticket number (auto-generated: TKT-YYYYMMDD-XXXXXX)
- Customer & Device references
- Items included, Problem description
- Phase (Open, Diagnostic, Waiting for Parts, Repairing, Finished, Cancelled)
- Device pickup tracking (picked_up, picked_up_date)
- Costs (estimated, actual)
- Timestamps (created, updated, completed)
- Relationships: notes, payments, phase_logs, services, invoice

### Service
- Service name, Description
- Price (charged to customer)
- Active status
- Multiple ticket_services relationship

### TicketService
- Service & Ticket references
- Quantity, Price
- Added timestamp

### SparePart
- Name, Description
- Cost (to shop), Selling price (to customer)
- Stock quantity, Active status
- Multiple invoice_items relationship

### Invoice
- Invoice number (auto-generated: INV-YYYYMMDD-XXXXXX)
- Ticket reference
- Subtotal (services), Spare parts total, Grand total
- Down payment received, Full payment received, Remaining balance
- Status (Draft, Issued, Partially Paid, Paid, Cancelled)
- Issued date, Due date, Paid date
- Invoice items relationship

### InvoiceItem
- Invoice & SparePart references
- Quantity, Unit price, Total price
- Added timestamp

### Payment
- Ticket reference
- Amount, Type (Down Payment, Full Payment, Additional Payment)
- Payment method, Notes
- User who recorded it
- Timestamp

### PhaseLog
- Ticket reference
- User (technician who made the change)
- Phase, Commentary
- Timestamp

### Note
- Ticket reference
- User (author)
- Type (General, Down Payment, Full Payment, Device Picked Up, Technical Update, Customer Communication)
- Content
- Timestamp

### CommonProblem
- Problem text (e.g., "Faulty harddrive", "Screen not turning on")
- Active status
- Timestamp

### Backup
- Backup name
- Backup data (JSON)
- File size
- Created by user reference
- Timestamp

## 💻 Usage Guide

### Creating a Repair Ticket

1. Click **"New Ticket"** on dashboard
2. **Search & Select Customer:**
   - Type customer name to search (minimum 2 characters)
   - Results sorted by most recently added
   - OR click **"Create New Customer"** to add inline
3. **Select Device:**
   - Device list updates based on selected customer
   - Search devices by brand/model
   - OR click **"Create New Device"** to add inline
4. **Fill Ticket Details:**
   - Items included with device
   - Problem description (autocomplete with common problems)
   - Optional: Assign technician
   - Optional: Record down payment
5. Submit to create ticket

### Managing Ticket Phases

1. Open ticket from dashboard
2. Click **"Update Phase"** button
3. Select new phase:
   - **Open** - Just received
   - **Diagnostic** - Examining device
   - **Waiting for Parts** - Waiting for components
   - **Repairing** - Currently fixing
   - **Finished** - Ready for pickup
   - **Cancelled** - Job cancelled
4. Add optional commentary
5. Save changes

### Creating Invoices

1. Open finished ticket
2. Add services:
   - Click **"Add Service"**
   - Select service from list
   - Confirm price
3. Add spare parts:
   - Click **"Add Spare Part"**
   - Enter quantity and unit price
4. Click **"Create Invoice"**
5. Review invoice details
6. Click **"Download PDF"** to generate professional invoice

### Managing Devices

**View All Devices:**
- Click **Devices** tab on main navigation

**Add Device to Customer:**
1. Go to customer detail page
2. Click **"Add Device"**
3. Enter device specifications
4. Save

**Edit Device:**
1. Click device from devices list or customer page
2. Click **"Edit"** button
3. Update details
4. Save

**Delete Device:**
1. Click device from devices list
2. Click **"Delete"** button
3. Confirm deletion

### Recording Payments

1. Open ticket
2. Scroll to **"Payments"** section
3. Click **"Record Payment"**
4. Enter:
   - Amount
   - Type (Down Payment, Full Payment, Additional Payment)
   - Payment method (Cash, Card, Check, Online)
   - Optional notes
5. Submit

### Managing Common Problems

**Admin Only:**
1. Go to **Admin > Common Problems**
2. Add new problems by entering text
3. Click **"Add"**
4. Remove problems by clicking **"Delete"**

These appear as quick-select options when creating tickets.

### User Management

**Create User:**
1. Go to **Admin > Manage Users > Create User**
2. Enter username, email (optional), full name, password
3. Assign roles (technician, receptionist, manager)
4. Click **"Create"**

**Edit User Permissions:**
1. Go to **Admin > Manage Users**
2. Click **"Edit"** on user
3. Assign roles
4. Grant permissions organized by category:
   - **Tickets** - create_ticket, view_ticket, edit_ticket, delete_ticket, add_note, update_phase, add_service, create_invoice
   - **Customers** - create_customer, view_customer, edit_customer, delete_customer, create_device, edit_device, delete_device
   - **Payments** - record_payment, view_payment, delete_payment
   - **Users** - create_user, view_user, edit_user, delete_user, manage_permissions
   - **Reports** - view_reports, export_data
5. Save changes

### Theme Settings

**User Preferences:**
1. Click profile name > **Profile & Theme**
2. Select **Theme** (Light/Dark)
3. Select **Color Scheme** (Blue, Green, Purple, Red, Orange)
4. Save changes

**Theme applies to:**
- Dashboard background
- Cards and panels
- Navigation bar
- Buttons and accents

### Backup & Restore

**Generate Backup:**
1. Go to **Admin > Backup**
2. Click **"System Backups"**
3. Click **"Download Backup"**
4. The system generates a JSON file containing customer and ticket data for download.

**Restore Backup:**
- Download backup JSON
- Use in new system installation

### Reports & Analytics

**View Reports:**
1. Click **Reports** tab
2. View monthly statistics:
   - Total tickets
   - Completed tickets
   - Total revenue
3. See recent ticket activity

## 🔐 User Roles & Permissions

### Admin
- Full system access
- Manage users and permissions
- Create/edit common problems
- Create and download backups

### Technician
- Create and update tickets
- Update ticket phases
- Add services to tickets
- Record payments
- View customer/device information

### Receptionist
- Create customers and devices
- Create tickets
- Record payments
- View reports

### Manager
- All access except user management
- Create and download backups
- View all reports
- Manage common problems

## ⚙️ Configuration

Edit `config.py` to change:
- Database URI (default: SQLite)
- Secret key (CHANGE IN PRODUCTION)
- Debug mode
- Session timeout
- Maximum upload size

## 🐛 Troubleshooting

### Database Issues
```bash
# Reset database (deletes all data!)
rm instance/shop.db
python app.py
```

### Missing Dependencies
```bash
pip install -r requirements.txt --upgrade
```

### Port Already in Use
```bash
# Run on different port
python -c "from app import create_app; app = create_app(); app.run(port=5001)"
```

## 📦 Deployment

### Production Checklist
- [ ] Change `SECRET_KEY` in `config.py`
- [ ] Set `DEBUG = False`
- [ ] Use PostgreSQL instead of SQLite
- [ ] Set up proper logging
- [ ] Configure HTTPS
- [ ] Set strong passwords
- [ ] Create database backups regularly
- [ ] Set up email notifications (optional)

### Deployment Platforms
- **Heroku:** Use Procfile and environment variables
- **AWS:** Deploy with Elastic Beanstalk or EC2
- **DigitalOcean:** Use App Platform or Droplet with Gunicorn
- **PythonAnywhere:** Simple hosting for Python apps

## 📄 License

GNU General Public License v3.0 - See LICENSE file for details

## 🤝 Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## 📞 Support

For issues, questions, or feature requests:
- Create an issue on GitHub
- Check existing issues for solutions
- Provide detailed description and steps to reproduce

## 🎯 Roadmap

Planned features:
- Email notifications for ticket updates
- SMS reminders for device pickup
- Multi-language support
- Advanced analytics and charting
- Customer portal (view own tickets)
- Integration with accounting software
- Mobile app
- API for third-party integrations

## 📝 Changelog

### Version 1.0.0 (Current)
- Initial release
- Complete ticket management system
- Customer and device tracking
- Invoice generation with PDF export
- Service and spare parts management
- Multi-theme support (light/dark)
- Customizable color schemes
- Role-based access control
- Database backup/restore
- Reports and analytics
- 24-hour time format
- Common problems quick-select

---

Made with ❤️ for repair shops everywhere
