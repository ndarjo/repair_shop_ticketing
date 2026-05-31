// Main JavaScript file for Repair Shop Ticketing System

// Auto-dismiss alerts after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });
});

// Confirm before deleting
function confirmDelete(msg) {
    return confirm(msg || 'Are you sure?');
}

// Format currency
function formatCurrency(value) {
    if (!value) return '$0.00';
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(value);
}