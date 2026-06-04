# Troubleshooting Guide

Common issues encountered during setup, deployment, or operation of the Repair Shop Ticketing System.

## 🐍 Python & Flask CLI Issues

### 1. `ModuleNotFoundError: No module named 'models'`
**Symptoms:** When running `flask seed`, `flask db migrate`, or starting the app, you see an `ImportError` or `ModuleNotFoundError` regarding the `models` module.

**Cause:** This usually occurs because the Python interpreter cannot find the `models.py` file in its search path. This happens if `FLASK_APP` is set to a full package path (e.g., `repair-shop-ticketing.app`) while running from within the directory, or if the environment isn't properly initialized.

**Solution:**
1. Navigate directly to the project root:
   ```bash
   cd repair-shop-ticketing/
   ```
2. Set the `FLASK_APP` environment variable to the local filename:
   ```bash
   export FLASK_APP=app.py
   # On Windows: set FLASK_APP=app.py
   ```
3. Run the command again. Python will now include the current directory in the search path, allowing the relative imports to work.

### 2. `Error: No such command 'seed'`
**Symptoms:** The Flask CLI does not recognize the custom `seed` or `reencrypt-pii` commands.

**Cause:** These commands are registered dynamically in the `create_app()` factory. If the application fails to import (due to the `ModuleNotFoundError` above), these commands are never registered.

**Solution:** Fix the import error first. Once the application loads successfully, the custom commands will be visible in `flask --help`.

---

## 🛡️ RBAC & Permissions

### 1. Technician cannot update Ticket Phase
**Symptoms:** The "Update Phase" button is missing or phase options in the dropdown are disabled for Technicians.

**Cause:** The `update_phase` permission was added to the code but the database has not been synchronized with the new permission mappings defined in `services/setup.py`.

**Solution:**
Synchronize the database permissions by running the seed command:
```bash
flask seed
```

---

## 🔐 Encryption & Security

### 1. `cryptography.fernet.InvalidToken`
**Symptoms:** Security error flashed when viewing customers or search fails to return results.
**Cause:** Mismatched `ENCRYPTION_KEY`. Refer to ENCRYPTION_MAINTENANCE.md for rotation procedures.