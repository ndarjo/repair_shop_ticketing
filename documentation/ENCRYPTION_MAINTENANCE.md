# Encryption Maintenance & Key Rotation

This document outlines the procedures for rotating the `ENCRYPTION_KEY` or decrypting data manually in the event of a configuration change.

## ⚠️ Critical Warning
Before performing any key rotation or data maintenance, **perform a full database backup**. If the encryption key is lost and data is not re-encrypted, the PII (Personally Identifiable Information) within the database will be permanently unrecoverable.

## 🔄 Rotating the Encryption Key

The system provides a specialized CLI command to migrate data from an old key to a new one without data loss. The logic is located in `services/setup.py`.

### Procedure:

1.  **Generate a New Key**:
    Run the key generator utility:
    ```bash
    python generate_keys.py
    ```
    Copy the new `ENCRYPTION_KEY` value.

2.  **Update Environment**:
    Open your `env.local` file. 
    - Keep your **OLD** key visible (copy it to a notepad).
    - Replace the `ENCRYPTION_KEY` value with the **NEW** key.

3.  **Run the Migration Tool**:
    Execute the following command, passing your **OLD** key as the argument:
    ```bash
    flask reencrypt-pii "YOUR_OLD_BASE64_KEY_HERE"
    ```

### How it works:
The tool initializes a temporary decryption engine using the provided old key. It iterates through all customers, decrypts their `phone` and `address` fields into memory, and then saves them back to the database. Upon saving, the model's `@setter` logic (in `models.py`) automatically uses the **NEW** key currently loaded in the environment to re-encrypt the data.

## 🔍 Rotating the Blind Index Salt

If you change the `BLIND_INDEX_SALT`, the data is still safe and readable, but **search functionality will break**. Existing `phone_hash` values will no longer match the hashes generated from new search queries.

To fix this after changing the salt:
1.  Run the `reencrypt-pii` command (even using the same key for both current and argument).
2.  This forces the setter logic to run: `self.phone_hash = self.get_search_hash(value)`, which regenerates the hashes using the new salt.

## 🛠️ Manual Decryption (Recovery)

If you need to extract data outside of the web interface (e.g., via a Python script), you can use the following logic:

```python
from cryptography.fernet import Fernet
cipher = Fernet("YOUR_ENCRYPTION_KEY")
plaintext = cipher.decrypt(encrypted_blob_from_db.encode()).decode()
```