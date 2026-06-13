# Repair Shop Ticketing System

A professional, production-ready management platform for modern repair shops. Built with **Flask** and **PostgreSQL**, it provides full lifecycle tracking, hardware inventory management, and real-time profitability analytics with enterprise-grade security.

---

## Prerequisites
- **Python:** 3.8+ (Fully compatible with Python 3.13)
- **Database:** PostgreSQL 12+
- **System Headers:** `libpq-dev` (Linux) or equivalent for database driver compilation.


## Installation & Setup

Follow these steps to get your environment running:

### 1. Clone and Environment Setup
```bash
git clone https://github.com/ndarjo/repair-shop-ticketing.git
cd repair_shop_ticketing

python3 -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
```

### 2. Install Dependencies
```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```
*Note: We use `pip-tools`. If you modify `requirements.in`, run `pip-compile` to update the lockfile.*

### 3. Configuration & Security Keys
The system requires specific environment variables and encryption keys to secure PII (Personally Identifiable Information).

1. **Create Environment File**:
   ```bash
   cp env.template env.local
   ```
2. **Generate Security Keys**:
   ```bash
   python generate_keys.py
   ```
3. **Update `env.local`**: Open the file and paste the generated `SECRET_KEY`, `ENCRYPTION_KEY`, and `BLIND_INDEX_SALT`. Ensure your `DATABASE_URL` matches your local PostgreSQL credentials.

### 4. Database & Localization Initialization
Before running the app, you must create the physical database in PostgreSQL and compile the translation catalogs.

```bash

# Drop previously made database
sudo -i -u postgres psql
drop database repair_shop WITH (FORCE);

# Create the PostgreSQL database (ensure Postgres is running)
createdb repair_shop || sudo -u postgres createdb repair_shop

# Compile translation catalogs (Required for non-English language support)
#extract translation file
python manage_translations.py extract

#update translation file
python manage_translations.py update

#initialize language, i.e french
python manage_translations.py init fr

#Auto-Translate: Fills in the blanks automatically.
python manage_translations.py translate

# After editing the new strings in your .po files, re-compile:
python manage_translations.py compile
```

### 5. Start the Application
```bash
python app.py
```

**First Run Actions:**
- The system will automatically create tables and seed default roles/permissions.
- It will create a default superuser with the credentials defined in your environment variables.
- Access the dashboard at `http://127.0.0.1:5000` or your Local IPv4 address if enabled in env.local.

---

## 📄 License

GNU General Public License v3.0 - See LICENSE file for details
