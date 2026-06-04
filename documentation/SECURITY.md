# Security & Data Privacy (GDPR Compliance)

This system is designed with a "Privacy by Design" approach to handle Personally Identifiable Information (PII) securely.

## 🔐 PII Encryption at Rest

Sensitive customer data (`phone` and `address`) is never stored in plaintext. We utilize **AES-256 encryption** via the `cryptography` library.

- **Algorithm**: Fernet (AES-256-CBC with HMAC-SHA256).
- **Key Management**: Controlled via the `ENCRYPTION_KEY` environment variable.
- **Model Implementation**: Handled transparently via Python `@property` decorators in `models.py`. Decryption occurs only at runtime when the field is accessed.

## 🔍 Searchable Encrypted Data (Blind Indexing)

To maintain high-performance search capabilities without decrypting every row in the database, we use **Blind Indexing**.

- When a phone number is saved, a one-way `SHA-256` hash is generated using a unique `BLIND_INDEX_SALT`.
- This hash is stored in the `phone_hash` column.
- When searching for a phone number, the system hashes the search term and performs an exact match against the `phone_hash` index.

## 🛡️ Role-Based Access Control (RBAC)

Access is governed by granular permissions assigned to roles. 

| Role | Key Capabilities |
| :--- | :--- |
| **Admin** | Full system control, backups, user deletion, global settings. |
| **Manager** | Reporting, customer management, inventory pricing. |
| **Technician** | Ticket updates, service/part addition, hardware spec edits. |
| **Receptionist** | Intake, customer creation, payment processing. |

Permissions are checked using the `@require_permission('name')` decorator, which accounts for both standard web requests and AJAX/JSON calls.

## 🌐 Web Hardening

- **CSRF Protection**: Enforced on all POST/PUT/DELETE requests via `Flask-WTF`.
- **Security Headers**: Managed by `Flask-Talisman`.
  - **HSTS**: Enforces HTTPS.
  - **CSP**: Restricts script/style execution to authorized CDNs (jsDelivr, Cloudflare).
- **Rate Limiting**: `Flask-Limiter` prevents brute-force attacks on the login endpoint.