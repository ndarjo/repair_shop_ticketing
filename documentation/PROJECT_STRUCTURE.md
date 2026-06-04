## Project Structure

```text
repair-shop-ticketing/
├── documentation/          # In-depth technical guides
│   ├── ARCHITECTURE.md     # System design patterns
│   ├── PROJECT_STRUCTURE.md # This file
│   ├── TRANSLATION.md      # i18n workflow and Babel guide
│   ├── TROUBLESHOOTING.md  # Common issues and debug steps
│   ├── RBAC_GUIDE.md       # Role-Based Access Control and permissions
│   ├── DATABASE.md         # Schema and relational mapping
│   └── SECURITY.md         # Encryption and RBAC details
├── app.py                  # Application factory, extensions & middleware
├── models.py               # Database schemas, AES-256 encryption & PII logic
├── config.py               # Environment configuration & directory auto-creation
├── setup.py                # Root-level CLI commands & initial data seeding
├── test_app.py             # Automated unit and integrity test suite
├── generate_keys.py        # Utility to generate SECRET_KEY and ENCRYPTION_KEY
├── manage_translations.py  # Automation script for the i18n/Babel workflow
├── babel.cfg               # Babel configuration for string extraction
├── requirements.in         # Top-level dependencies for pip-tools
├── requirements.txt        # Pinned dependency lock file
├── env.template            # Template for environment variables
├── env.local               # Local environment secrets (Git-ignored)
├── messages.pot            # i18n translation source template
├── routes/                 # Web Blueprints (Controllers)
│   ├── admin.py            # System & branch management
│   ├── auth.py             # Auth & User Profile management
│   ├── customer.py         # Customer CRM management
│   ├── device.py           # Device repository and search
│   ├── main.py             # Dashboard & health checks
│   ├── setup.py            # Onboarding/Setup wizard logic
│   ├── report.py           # Financial & performance reporting
│   ├── ticket.py           # Repair lifecycle management
│   └── utils.py            # RBAC decorators & decimal helpers
├── services/               # Business Logic & Orchestration
│   ├── backup.py           # Logical data export logic
│   ├── core.py             # Financial, Inventory, and Backup services
│   ├── setup.py            # Scheduler registration & background tasks
│   └── ticket.py           # Specialized repair ticket logic
├── static/                 # Static web assets
│   ├── css/                # Application stylesheets
│   │   └── style.css       # Theme-aware CSS
│   ├── js/                 # Client-side JavaScript
│   │   └── main.js         # Theme engine, AJAX search & UI logic
│   └── uploads/            # Dynamic assets (Shop logos, etc.)
├── templates/              # Jinja2 HTML templates
│   ├── base.html           # Master layout with navigation & theme support
│   ├── macros/             # Reusable UI components
│   │   └── pagination.html # Standardized list navigation
│   ├── admin/              # System & branch management
│   │   ├── backup.html                 # Database backup and restore interface
│   │   ├── create_user.html            # New staff account creation form
│   │   ├── dashboard.html              # Admin-specific overview and KPIs
│   │   ├── edit_user.html              # User profile and permission editor
│   │   ├── system_status.html          # Detailed diagnostic & health info
│   │   ├── locations.html              # Physical branch management
│   │   ├── manage_common_problems.html # Intake quick-select configuration
│   │   ├── manage_parts.html           # Spare parts & stock levels
│   │   ├── manage_services.html        # Service catalog management
│   │   ├── manage_users.html           # Staff directory management
│   │   └── settings.html               # Branch-specific branding and config
│   ├── Auth/               # Identity & Access management
│   │   └── login.html      # Secure staff login interface
│   │   └── profile.html    # User settings & preferences
│   ├── customers/          # CRM views
│   │   ├── customers.html  # Customer directory
│   │   ├── customer_detail.html # 360 view of customer data
│   │   └── new_customer.html # Customer intake form
│   ├── devices/            # Hardware repository
│   │   ├── devices.html    # Inventory list
│   │   ├── device_detail.html  # Comprehensive hardware history and specs
│   │   ├── new_device.html # Hardware registration
│   │   └── edit_device.html # Specifications editor
│   ├── errors/             # Custom error handling
│   │   ├── 403.html        # Access Denied / Permission Error
│   │   ├── 404.html        # Page Not Found
│   │   └── 500.html        # Internal Server Error
│   ├── main/               # General views
│   │   └── dashboard.html  # Central repair workspace
│   ├── onboarding/         # Setup wizard
│   │   ├── base.html       # Minimalist layout for setup (no nav/sidebar)
│   │   └── setup.html      # Initial shop configuration
│   ├── reports/            # Analytics
│   │   ├── reports.html    # General performance KPIs
│   │   └── finance_report.html # Monthly revenue & hardware cost
│   ├── tickets/             # Repair lifecycle views
│   │   ├── new_ticket.html  # Customer intake interface
│   │   ├── ticket_detail.html # 360 management workspace
│   │   ├── ticket_form.html # Reusable form component (Partial)
│   │   ├── tickets_list.html # Advanced ticket repository/search
│   │   ├── edit_ticket.html # Intake data correction interface
│   │   └── invoice.html     # Web-viewable customer receipt
├── translations/           # i18n message catalogs
│   └── <lang_code>/        # Locale directory (e.g., /id, /es, /fr)
│       └── LC_MESSAGES/    # Standard Gettext directory
│           ├── messages.po # Source translation strings
│           └── messages.mo # Compiled binary used by the app
├── instance/               # Local SQLite/PostgreSQL instance data
├── logs/                   # Application runtime log files
│   └── repair_shop.log     # Rotating application log file
└── backups/                # Automated database backups
    └── backup_*.json       # Time-stamped system logical data exports
```
