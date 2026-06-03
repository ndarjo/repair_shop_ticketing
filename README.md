# Repair Shop Ticketing System

A professional, production-ready management platform for modern repair shops. Built with **Flask** and **PostgreSQL**, it provides full lifecycle tracking, hardware inventory management, and real-time profitability analytics with enterprise-grade security.

---

## 🚀 Core Capabilities

### 🛠️ Repair Management
- **Lifecycle Tracking:** 8 distinct phases (from Intake to Pickup) with automated audit logs.
- **Smart Intake:** AJAX-powered search for customers/devices and quick-select "Common Problems."
- **Timeline:** Technical notes, phase logs, and internal team communications.

### 💼 CRM & Inventory
- **Customer Profiles:** Comprehensive management with encrypted PII (Personally Identifiable Information).
- **Hardware Specs:** Detailed tracking of CPU, RAM, and Serial Numbers linked to repair history.
- **Catalog:** Standardized services and spare parts with retail vs. wholesale pricing.

### 📈 Financial Intelligence
- **Net Profit:** Real-time calculation of revenue minus actual hardware wholesale costs.
- **Payment Processing:** Support for down payments, partials, and settlements with change calculation.
- **Invoicing:** Professional invoice generation and payment history.

### 🔐 Security & Compliance
- **RBAC:** Granular Role-Based Access Control (Admin, Manager, Tech, Reception).
- **Web Hardening:** CSRF protection, secure HTTP headers (HSTS), and automated daily backups.

## 📋 Prerequisites
- **Python:** 3.8+ (Fully compatible with Python 3.13)
- **Database:** PostgreSQL 12+
- **Cache/NoSQL:** Redis (Optional, required if `RATELIMIT_STORAGE_URI` is set to redis)
- **PostgreSQL Client Tools:** `pg_dump` and `pg_restore` (required for system backups).
- **System Headers:** `libpq-dev` (Linux) or equivalent for database driver compilation.

## 🚀 Installation & Setup
```bash
# 1. Clone the repository
git clone https://github.com/ndarjo/repair-shop-ticketing.git
cd repair-shop-ticketing

# 2. Setup virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate     # Windows

# 3. Install dependencies
pip install --upgrade pip setuptools wheel && pip install -r requirements.txt

# 4. Configure environment
cp env.template env.local
# Open env.local and update DB_PASSWORD and INITIAL_ADMIN_PASSWORD.

# Generate unique security keys:
python generate_keys.py
# Copy the generated keys into your env.local file.

# 5. Initialize Database & Run
createdb repair_shop || sudo -u postgres createdb repair_shop
python app.py
```

The application will be available at `http://localhost:5000`

## 🔐 Security & Data Protection

This system is designed with a "Security by Design" approach to handle sensitive customer data:

### PII Encryption (AES-256)
Customer **Phone Numbers** and **Addresses** are encrypted at rest using `cryptography.fernet` (AES-256 in CBC mode with HMAC). Even if your database is compromised, this PII remains unreadable without the `ENCRYPTION_KEY`.

### Searchable Encrypted Fields (Blind Index)
To allow technicians to search for customers by phone number without decrypting every record, the system uses a **Blind Index**. This is a one-way SHA-256 hash of the PII combined with a unique `BLIND_INDEX_SALT`. The database stores the hash, allowing for fast, exact-match searches while keeping the actual data encrypted.

### ⚠️ Critical Warning: Key Persistence
Your `ENCRYPTION_KEY` and `BLIND_INDEX_SALT` are generated during setup. 
- **Never lose these keys:** If you lose your keys, you will be unable to decrypt existing customer data. 
- **Key Rotation:** If you change your `ENCRYPTION_KEY` in `env.local`, existing records will become inaccessible and trigger a security error.
- **Database Migrations:** When moving to a new server, you **must** copy your keys exactly as they are in your current `.env` file.

Use `python generate_keys.py` to create your unique security credentials.

## 🌐 Internationalization (i18n)

The system supports dynamic language discovery based on compiled translation files. To manage translations, the system uses **Flask-Babel** and a provided helper script.

### Workflow for Adding a New Language (e.g., French `fr`)

1. **Initialize:** Create the translation catalog.
   ```bash
   python manage_translations.py init fr
   ```
2. **Translate:** Open `translations/fr/LC_MESSAGES/messages.po` and fill in the translated strings in `msgstr`.
3. **Compile:** Generate the machine-readable files. **Note: The language selection in Profile and Onboarding only lists languages that have been compiled.**
   ```bash
   python manage_translations.py compile
   ```

### Updating Existing Translations
If you modify the source code or templates, use the update command to scan for new strings and merge them into existing catalogs:
```bash
python manage_translations.py update
# After editing the new strings in your .po files, re-compile:
python manage_translations.py compile
```

## 🔑 Default Credentials

After first run, you'll have a default superuser account:
- **Username:** admin
- **Password:** Value of `INITIAL_ADMIN_PASSWORD` (defaults to `change-me-immediately`)

⚠️ **Important:** Change the password immediately in production!

## 📁 Project Structure

```text
repair-shop-ticketing/
├── app.py                      # Main Flask application & initialization
├── models.py                   # Database models & schema
├── routes.py                   # Route handlers & business logic
├── config.py                   # Configuration settings
├── requirements.txt            # Python dependencies
├── test_app.py                 # Automated test suite
├── README.md                   # This file
├── templates/                  # HTML templates
│   └── ...                    # Organized views (auth, admin, ticket, etc.)
└── static/                     # Static files
    ├── css/style.css          # Theme-aware stylesheet
    └── js/main.js             # AJAX search & theme engine
```


### 🌐 LAN vs. Internet Deployment
By default, production mode enforces HTTPS for security.
- **For Internet (HTTPS):** No extra configuration needed (ensure your server has an SSL certificate).
- **For LAN only (HTTP):** Set the environment variable `SESSION_COOKIE_SECURE=False`. This disables HTTPS enforcement, allowing technicians to access the app via a local IP (e.g., `http://192.168.1.50:5000`) without SSL errors.

To switch environments, set `FLASK_CONFIG=production`.

## 🐛 Troubleshooting

### Database Issues

**Error: Failed to build psycopg[binary] or libpq-fe.h: No such file or directory**
This happens when system-level PostgreSQL development headers are missing, preventing the compilation of the database driver. `psycopg[binary]` requires these headers to build its C extensions.

- **Ubuntu/Debian:** `sudo apt-get install libpq-dev python3-dev`
- **RHEL/CentOS/Fedora:** `sudo dnf install postgresql-devel python3-devel gcc`
- **macOS:** `brew install postgresql`
- **Windows:** Install Visual C++ Build Tools.

After installing the system libraries, run: `pip install --upgrade pip setuptools wheel && pip install -r requirements.txt`.

```bash
# Reset database (deletes all data!)
dropdb repair_shop && createdb repair_shop
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
- [ ] Generate unique `ENCRYPTION_KEY`
- [ ] Use PostgreSQL instead of SQLite
- [ ] Set up proper logging
- [ ] Configure HTTPS
- [ ] Set strong passwords
- [ ] Create database backups regularly
- [ ] Set up email notifications (optional)


## 📄 License

GNU General Public License v3.0 - See LICENSE file for details

## 🎯 Roadmap

Planned features:
- **PDF Invoice Generation** (currently placeholder)
- **Database Migrations:** Integrate `Flask-Migrate` for non-destructive schema updates.

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
