## Project Structure

```text
repair-shop-ticketing/
├── documentation/          # In-depth technical guides
│   ├── ARCHITECTURE.md     # System design patterns
│   ├── PROJECT_STRUCTURE.md # This file
│   ├── TRANSLATION.md      # i18n workflow and Babel guide
│   ├── TROUBLESHOOTING.md  # Common issues and debug steps
│   ├── ENCRYPTION_MAINTENANCE.md # Key rotation and data recovery guide
│   ├── RBAC_GUIDE.md       # Role-Based Access Control and permissions
│   ├── DATABASE.md         # Schema and relational mapping
│   └── SECURITY.md         # Encryption and RBAC details
├── app.py                  # Application factory, extensions & middleware
├── __init__.py             # Core package initialization
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
├── .gitignore              # Files and patterns ignored by Git
├── messages.pot            # i18n translation source template
├── routes/                 # Web Blueprints (Controllers)
│   ├── __init__.py         # Blueprint hub & exports
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
│   ├── core.py             # Financial, Inventory, CRM, and Document services
│   ├── setup.py            # Scheduler registration & background tasks
│   └── ticket.py           # Specialized repair ticket logic
├── static/                 # Static web assets
│   ├── css/                # Application stylesheets
│   │   └── style.css       # Theme-aware CSS
│   ├── js/                 # Client-side JavaScript
│   │   └── main.js         # Theme engine, AJAX search & UI logic
│   └── uploads/            # Dynamic assets (Shop logos, etc.)
│       └── logos/          # Branch-specific branding assets
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
│   │   ├── manage_users.html           # Staff directory management
│   │   └── settings.html               # Branch-specific branding and config
│   ├── common_problem/      # Intake quick-select configuration views
│   │   └── manage_common_problems.html # Intake quick-select configuration
│   ├── parts/               # Spare parts & inventory views
│   │   └── manage_parts.html           # Spare parts & stock levels
│   ├── services/            # Service catalog views
│   │   └── manage_services.html        # Service catalog management
│   ├── Auth/               # Identity & Access management...
... (rest of tree remains standard)
```
