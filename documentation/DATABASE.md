# Database Schema & Models

The system uses PostgreSQL to manage relational repair data. Below are the primary entities:

### `locations`
The root entity for multi-tenancy. Represents physical shop branches.

### `users`
Staff accounts linked to a `location`. Stores preferences (theme, language) and password hashes.

### `customers`
The CRM entity. Stores encrypted PII and identifies the customer's home branch.

### `devices`
The hardware repository. Tracks serial numbers and technical specs (CPU, RAM, Storage) independently of tickets. This allows for historical tracking of the same physical unit over multiple years.

### `tickets`
The central transaction record. 
- Tracks the current phase.
- Aggregates totals from `ticket_services` and `invoices`.
- Provides a `timeline` property that merges `phase_logs` and `notes`.

### `invoices` & `payments`
The financial sub-system. 
- `invoices` track the billable amount for parts.
- `payments` track actual cash/card flow. 
- Balance due is calculated dynamically as `invoice.total - sum(payments)`.