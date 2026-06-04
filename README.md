# Repair Shop Ticketing System

A professional, production-ready management platform for modern repair shops. Built with **Flask** and **PostgreSQL**, it provides full lifecycle tracking, hardware inventory management, and real-time profitability analytics with enterprise-grade security.

---

## 🚀 Core Capabilities

### 🛠️ Repair Management
- **Lifecycle Tracking:** 8 distinct phases (from Intake to Pickup) with automated audit logs.
- **Smart Intake:** AJAX-powered search for customers/devices and quick-select "Common Problems."
- **Multi-Tenancy:** Physical branch isolation ensures technicians only access tickets for their specific location.

### 💼 CRM & Inventory
- **Encrypted CRM:** Customer data is protected via AES-256 encryption (PII) with Blind Indexing for high-performance searchable encrypted fields.
- **Device Repository:** Detailed hardware specs (CPU, RAM, Serial Numbers) linked to customer history and specific repair tickets.
- **Inventory Control:** Managed catalog of services and spare parts with location-based pricing and stock tracking.

### 📈 Financial Intelligence
- **Net Profit:** Real-time calculation of revenue minus actual hardware wholesale costs.
- **Payment Processing:** Support for down payments, partials, and settlements with change calculation.
- **Invoicing:** Professional invoice generation and payment history.

### 🔐 Security & Compliance
- **RBAC:** Granular Role-Based Access Control (Admin, Manager, Tech, Reception).
- **Web Hardening:** CSRF protection, secure HTTP headers via Talisman (HSTS, CSP), and rate limiting.
- **Data Privacy:** AES-256 PII encryption and HMAC-SHA256 blind indexing for secure, searchable data.

## 📋 Prerequisites
- **Python:** 3.8+ (Fully compatible with Python 3.13)
- **Database:** PostgreSQL 12+
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
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

### 📦 Dependency Management
We use `pip-tools` to manage dependencies.
- **requirements.in**: Direct project dependencies.
- **requirements.txt**: Compiled lock file with pinned versions.

To update the lock file after adding a package to `requirements.in`:
`pip install pip-tools && pip-compile requirements.in`

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

⚠️ **Security:** Always set a unique, strong password in your environment configuration before deployment.

## 📁 Project Structure

```text
repair-shop-ticketing/
├── app.py              # Application factory & extension registry
├── models.py           # SQLAlchemy domain models & encryption logic
├── config.py           # Environment-based configuration profiles
├── routes/             # Blueprint-based controllers
│   ├── auth.py         # Session management & user profiles
│   ├── ticket.py       # Repair lifecycle & financial actions
│   └── utils.py        # RBAC decorators & type-safe helpers
├── services/           # Business logic & system orchestration
│   ├── core.py         # Financial, Inventory, Reporting, and Backup services
│   ├── ticket.py       # Specialized repair ticket lifecycle services
│   └── setup.py        # Database seeding, CLI commands, & scheduler tasks
├── static/             # Static assets
│   ├── css/style.css   # Theme-aware stylesheet
│   └── js/main.js      # AJAX search & theme engine
├── templates/          # Jinja2 templates organized by feature
├── translations/       # i18n message catalogs
├── requirements.in     # Direct project dependencies
├── requirements.txt    # Pinned production dependencies
├── env.template        # Template for environment variables
├── generate_keys.py    # Utility to generate security & encryption keys
├── manage_translations.py # Translation workflow automation script
└── instance/           # Instance-specific data (logs, backups, local DB)
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

### 🚀 Final Checklist

#### 1. Security & Secrets
- [ ] **Rotate Keys:** Run `python generate_keys.py` and update `SECRET_KEY`, `ENCRYPTION_KEY`, and `BLIND_INDEX_SALT` in `env.local`.
- [ ] **Re-encrypt PII:** If `ENCRYPTION_KEY` is changed, run `flask reencrypt-pii <OLD_ENCRYPTION_KEY>` to update existing customer data.
- [ ] **Admin Password:** Set a unique `INITIAL_ADMIN_PASSWORD` in environment variables before the first run.
- [ ] **Disable Debug:** Ensure `FLASK_CONFIG=production` is set in the environment.

#### 2. Database (PostgreSQL)
- [ ] **Dedicated User:** Avoid using the `postgres` superuser. Create a specific user with `GRANT` only on the `repair_shop` database.
- [ ] **Client Tools:** Verify `pg_dump` is in the system path for the automated backup scheduler.
- [ ] **Migrations:** If you have existing data, ensure you have initialized `Flask-Migrate` for schema updates.
- [ ] **Initialize Migrations:** Run `flask db init`, `flask db migrate`, `flask db upgrade` to set up database versioning.

#### 3. Networking & Web Server
- [ ] **WSGI Server:** Use **Gunicorn** or **Waitress** instead of the built-in Flask development server.
  - *Example:* `gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app()"`
- [ ] **Reverse Proxy:** Use **Nginx** or **Apache** to handle SSL termination and static file serving.
- [ ] **SSL (Online):** If public-facing, set `SESSION_COOKIE_SECURE=True` and install a certificate (e.g., Let's Encrypt).
- [ ] **LAN Access:** If local-only without SSL, set `SESSION_COOKIE_SECURE=False` and `HOST=0.0.0.0`.

#### 4. System Maintenance
- [ ] **Redis:** Ensure Redis is running and `RATELIMIT_STORAGE_URI` is configured to prevent in-memory limit resets.
- [ ] **Translations:** Run `python manage_translations.py compile` to build your `.mo` files.
- [ ] **Logging:** Configure external logging aggregation if `LOG_AGGREGATION_URI` is set.
- [ ] **Logs:** Check the `/logs` directory and ensure the system user has write permissions.
- [ ] **Cron:** Verify the `backups/` folder is writeable by the app for the 2:00 AM daily task.

## 📄 License

GNU General Public License v3.0 - See LICENSE file for details

## 🎯 Roadmap

Planned features:
- **PDF Invoice Generation:** Fully implemented receipt-style PDF engine.
- **Database Migrations:** Integrated `Flask-Migrate` for non-destructive schema updates.

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
