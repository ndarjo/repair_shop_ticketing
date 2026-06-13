# Data Flow (Screen ↔ Data Source)

```mermaid
%%{init:{'theme':'base','themeVariables':{'background':'#060810','primaryColor':'#2a4055','primaryTextColor':'#f8fafc','primaryBorderColor':'#1e4060','lineColor':'#f59e0b','secondaryColor':'#0f172a','tertiaryColor':'#1a0a20','attributeBackgroundColorEven':'#ffffff','attributeBackgroundColorOdd':'#f1f5f9','textColor':'#1e293b','nodeBorder':'#1e4060','clusterBkg':'#0a0e1a','fontFamily':'JetBrains Mono','fontSize':'14'}}}%%
erDiagram
%% table:locations path:models.py
%% table:users path:models.py
%% table:roles path:models.py
%% table:permissions path:models.py
%% table:customers path:models.py
%% table:devices path:models.py
%% table:tickets path:models.py
%% table:services path:models.py
%% table:ticket_services path:models.py
%% table:spare_parts path:models.py
%% table:common_problems path:models.py
%% table:notes path:models.py
%% table:phase_logs path:models.py
%% table:invoices path:models.py
%% table:payments path:models.py
%% table:invoice_items path:models.py
%% table:shop_settings path:models.py
  locations {
    Integer id PK
    Column name
    Text address
    Column phone
    Column email
    DateTime created_at
  }
  users {
    Integer id PK
    Column username
    Column email
    Column password_hash
    Column full_name
    Boolean is_superuser
    Boolean is_active
    Column theme_preference
    Column color_theme
    Column language_preference
    Column currency
    Integer currency_decimals
    DateTime created_at
    Integer_FK location_id FK
  }
  roles {
    Integer id PK
    Column name
    Text description
    DateTime created_at
  }
  permissions {
    Integer id PK
    Column name
    Text description
    Column category
    DateTime created_at
  }
  customers {
    Integer id PK
    Column name
    Text _phone_encrypted
    Integer_FK location_id FK
    Text _address_encrypted
    Column phone_hash
    DateTime created_at
    DateTime updated_at
  }
  devices {
    Integer id PK
    Integer_FK customer_id FK
    Column device_type
    Column brand
    Column model_number
    Column cpu
    Column ram
    Column storage_type
    Column storage_capacity
    Column serial_number
    Column color
    Text notes
    DateTime created_at
  }
  tickets {
    Integer id PK
    Column ticket_number
    Integer_FK customer_id FK
    Integer_FK device_id FK
    Integer_FK assigned_to FK
    Integer_FK creator_id FK
    Integer_FK location_id FK
    Text items_included
    Text problem_description
    Column current_phase
    Boolean is_archived
    Boolean device_picked_up
    DateTime picked_up_date
    Column estimated_cost
    Column actual_cost
    DateTime created_at
  }
  services {
    Integer id PK
    Column name
    Text description
    Column price
    Boolean is_active
    Integer_FK location_id FK
    DateTime created_at
  }
  ticket_services {
    Integer id PK
    Integer_FK ticket_id FK
    Integer_FK service_id FK
    Integer quantity
    Column price_charged
  }
  spare_parts {
    Integer id PK
    Column name
    Text description
    Column cost
    Column selling_price
    Integer stock_quantity
    Boolean is_active
    Integer_FK location_id FK
    DateTime created_at
  }
  common_problems {
    Integer id PK
    Column problem_text
    Integer_FK location_id FK
    Boolean is_active
    DateTime created_at
  }
  notes {
    Integer id PK
    Integer_FK ticket_id FK
    Integer_FK user_id FK
    Column note_type
    Text content
    Boolean is_internal
    DateTime created_at
  }
  phase_logs {
    Integer id PK
    Integer_FK ticket_id FK
    Integer_FK user_id FK
    Column old_phase
    Column new_phase
    DateTime changed_at
  }
  invoices {
    Integer id PK
    Column invoice_number
    Integer_FK ticket_id FK
    Column total_amount
    Column status
    DateTime created_at
  }
  payments {
    Integer id PK
    Integer_FK invoice_id FK
    Integer_FK ticket_id FK
    Integer_FK user_id FK
    Column amount
    Column payment_method
    Column transaction_reference
    DateTime paid_at
  }
  invoice_items {
    Integer id PK
    Integer_FK invoice_id FK
    Integer_FK spare_part_id FK
    Column description
    Integer quantity
    Column cost_price
    Column unit_price
    Column total_price
  }
  shop_settings {
    Integer id PK
    Integer_FK location_id FK
    Column shop_name
    Text shop_address
    Column shop_phone
    Column shop_email
    Column logo_path
    Boolean setup_completed
  }
  users }o--|| locations : "location_id"
  customers }o--|| locations : "location_id"
  devices }o--|| customers : "customer_id"
  tickets }o--|| customers : "customer_id"
  tickets }o--|| devices : "device_id"
  tickets }o--|| users : "assigned_to"
  tickets }o--|| users : "creator_id"
  tickets }o--|| locations : "location_id"
  services }o--|| locations : "location_id"
  ticket_services }o--|| tickets : "ticket_id"
  ticket_services }o--|| services : "service_id"
  spare_parts }o--|| locations : "location_id"
  common_problems }o--|| locations : "location_id"
  notes }o--|| tickets : "ticket_id"
  notes }o--|| users : "user_id"
  phase_logs }o--|| tickets : "ticket_id"
  phase_logs }o--|| users : "user_id"
  invoices }o--|| tickets : "ticket_id"
  payments }o--|| invoices : "invoice_id"
  payments }o--|| tickets : "ticket_id"
  payments }o--|| users : "user_id"
  invoice_items }o--|| invoices : "invoice_id"
  invoice_items }o--|| spare_parts : "spare_part_id"
  shop_settings }o--|| locations : "location_id"
```
