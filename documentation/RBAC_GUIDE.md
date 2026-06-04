# Role-Based Access Control (RBAC) Guide

This document details the granular permission system used to secure the Repair Shop Ticketing System.

## 🛡️ Permission Hierarchy

Permissions are defined as string tokens in the database and assigned to roles. The system uses a "Role-Inherited" model: users are assigned roles, and their effective permissions are the sum of all permissions linked to those roles.

### Available Permissions
| Token | Description |
| :--- | :--- |
| `view_customer` / `create_customer` | Access to CRM data and intake |
| `edit_customer` / `delete_customer` | Management of client records |
| `view_ticket` / `create_ticket` | Basic repair lifecycle access |
| `edit_ticket` | Modify problem descriptions and assignments |
| `update_phase` | Advance a ticket through the 8-phase lifecycle |
| `delete_ticket` | Permanent removal of repair records |
| `mark_as_paid` | Permission to set invoice status to 'Fully Paid' |
| `mark_as_taken` | Permission to set ticket phase to 'Already Taken' (Pickup) |
| `view_reports` | Access to financial and performance analytics |
| `manage_settings` | Control over shop branding and catalog pricing |
| `process_payments` | Record payments and issue refunds |
| `manage_inventory` | Adjust stock levels and catalog items |
| `create_device` / `edit_device` | Management of hardware specs |

## 👥 Default Roles & Mappings

The following mappings are initialized during the system seeding process (`flask seed`):

- **Admin**: Possesses all permissions in the system.
- **Manager**: Full operational control. Can delete customers but is restricted from deleting tickets or hardware to preserve history.
- **Technician**: Focused on the workbench. Can view records, update repair progress (`update_phase`), edit hardware specs, and manage parts stock.
- **Receptionist**: Focused on the front desk. Handles intake, customer creation, payments, and the final checkout/pickup process.

## 🔄 Updating Permissions

Permissions are orchestrated in `services/setup.py`. If you modify the `role_permissions` dictionary in that file, you must re-run the seed command to synchronize the database:

```bash
flask seed
```

## 💻 Technical Implementation

Access is enforced at the routing level using the `@require_permission` decorator:
```python
@ticket_bp.route('/update_phase/<int:ticket_id>', methods=['POST'])
@require_permission('update_phase')
def update_phase(ticket_id):
    ...
```