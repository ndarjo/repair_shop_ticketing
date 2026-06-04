from services.setup import (
    initialize_roles_and_permissions,
    initialize_default_data,
    initialize_superuser,
    register_scheduler_tasks,
    register_cli_commands
)

__all__ = [
    'initialize_roles_and_permissions',
    'initialize_default_data',
    'initialize_superuser',
    'register_scheduler_tasks',
    'register_cli_commands'
]

# This file now serves as a bridge for setup logic. 
# Most functionality is imported from services/setup.py to maintain DRY principles.
# Direct calls to these functions are made in app.py during the application factory lifecycle.