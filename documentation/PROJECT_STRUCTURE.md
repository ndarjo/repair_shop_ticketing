```
repair_shop_ticketing
├──documentation
│   ├──ARCHITECTURE.md
│   ├──DATABASE.md
│   ├──ENCRYPTION_MAINTENANCE.md
│   ├──PROJECT_STRUCTURE.md
│   ├──RBAC_GUIDE.md
│   ├──SECURITY.md
│   ├──TRANSLATION.md
│   └──TROUBLESHOOTING.md
├──routes
│   ├──__init__.py
│   ├──admin.py
│   ├──auth.py
│   ├──customer.py
│   ├──device.py
│   ├──inventory.py
│   ├──main.py
│   ├──pos.py
│   ├──report.py
│   ├──services.py
│   ├──setup.py
│   ├──ticket.py
│   └──utils.py
├──services
│   ├──__init__.py
│   ├──backup.py
│   ├──core.py
│   ├──setup.py
│   └──ticket.py
├──static
│   ├──css
│   │   └──style.css
│   ├──js
│   │   ├──finance_report.js
│   │   ├──locations.js
│   │   ├──main.js
│   │   ├──new_ticket.js
│   │   ├──ticket_detail.js
│   │   └──ticket_search.js
│   └──uploads
│   │   └──logos
│   │   │   ├──logo_loc_1_favicon.png
│   │   │   └──logo_loc_3_favicon.png
├──templates
│   ├──admin
│   │   ├──backup.html
│   │   ├──create_user.html
│   │   ├──dashboard.html
│   │   ├──edit_user.html
│   │   ├──locations.html
│   │   ├──manage_users.html
│   │   ├──settings.html
│   │   └──system_status.html
│   ├──Auth
│   │   ├──login.html
│   │   └──profile.html
│   ├──common_problem
│   │   └──manage_common_problems.html
│   ├──customers
│   │   ├──customer_detail.html
│   │   ├──customers.html
│   │   ├──edit_customer.html
│   │   └──new_customer.html
│   ├──devices
│   │   ├──device_detail.html
│   │   ├──devices.html
│   │   ├──edit_device.html
│   │   └──new_device.html
│   ├──errors
│   │   ├──400.html
│   │   ├──401.html
│   │   ├──403.html
│   │   ├──404.html
│   │   ├──413.html
│   │   ├──415.html
│   │   ├──500.html
│   │   └──503.html
│   ├──macros
│   │   └──pagination.html
│   ├──main
│   │   └──dashboard.html
│   ├──onboarding
│   │   ├──base.html
│   │   └──setup.html
│   ├──parts
│   │   └──manage_parts.html
│   ├──pos
│   │   ├──cart.html
│   │   ├──history.html
│   │   └──index.html
│   ├──reports
│   │   ├──finance_report.html
│   │   └──reports.html
│   ├──services
│   │   └──manage_services.html
│   ├──tickets
│   │   ├──edit_ticket.html
│   │   ├──invoice.html
│   │   ├──new_ticket.html
│   │   ├──ticket_detail.html
│   │   ├──ticket_form.html
│   │   └──tickets_list.html
│   └──base.html
├──translations
│   └──id
│   │   └──LC_MESSAGES
│   │   │   └──messages.po
├──.codebase-viz
│   ├──cache.json
│   ├──db-screen.md
│   ├──rendering.md
│   └──screen-component.md
├──__init__.py
├──app.py
├──babel.cfg
├──config.py
├──env.template
├──generate_keys.py
├──LICENSE
├──manage_translations.py
├──messages.pot
├──models.py
├──README.md
├──requirements.in
├──requirements.txt
├──setup.py
├──test_app.py
└──.gitignore
```