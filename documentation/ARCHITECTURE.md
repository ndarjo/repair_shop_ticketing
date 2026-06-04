# System Architecture

The Repair Shop Ticketing System is built on a modular, service-oriented architecture designed for scalability and data integrity.

## 🏗️ Core Design Patterns

### 1. Application Factory (`app.py`)
We use the Flask Application Factory pattern. This allows for easy environment switching (Development, Testing, Production) and prevents circular dependencies by initializing extensions and blueprints within a scoped function.

### 2. Service Layer (`services/`)
Business logic is strictly separated from the routing layer. 
- **`FinancialService`**: Handles complex invoice calculations and payment lifecycle.
- **`InventoryService`**: Manages stock levels and part attachments to tickets.
- **`RepairTicketService`**: Manages the 8-phase lifecycle and automated audit logging.

### 3. Blueprints (`routes/`)
The UI is divided into functional modules:
- `admin`: System-wide settings and staff management.
- `ticket`: The main repair workspace.
- `customer/device`: CRM and hardware repository.

## 🏢 Multi-Tenancy (Physical Branches)

The system implements logical multi-tenancy through a `location_id` column found on:
- `Users`
- `Customers`
- `Tickets`
- `Inventory`

### Data Isolation
Technicians are scoped to their `current_user.location_id`. All database queries are filtered by this ID to ensure that staff members cannot see or modify records belonging to a different branch. Superusers bypass these filters for global management.

## 🔄 Lifecycle of a Repair

1. **Intake**: Customer and Device are identified or created. A Ticket is generated with an 'Open' status.
2. **Diagnostic**: Technician evaluates the unit and records technical notes.
3. **Quoting**: Services and Parts are added. An `Invoice` is generated in `Draft` or `Unpaid` status.
4. **Repairing**: Work is performed; stock levels for parts are automatically decremented.
5. **Finished**: Customer is notified via external systems (or manual check).
6. **Settlement**: Final payments are recorded; change is calculated if necessary.
7. **Pickup**: Ticket is marked as 'Already Taken', locking the record from further modification.