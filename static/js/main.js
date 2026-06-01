// ========================================
// REPAIR SHOP TICKETING SYSTEM
// Main JavaScript for Theme Management
// ========================================

/**
 * Apply theme to the page
 * @param {string} theme - 'light' or 'dark'
 */
function applyTheme(theme) {
    const html = document.documentElement;
    const body = document.body;
    
    // Update data attribute
    html.dataset.theme = theme;
    
    // Update body class
    body.classList.remove('theme-light', 'theme-dark');
    body.classList.add(`theme-${theme}`);
    
    // Save to localStorage
    localStorage.setItem('theme', theme);
}

/**
 * Apply color scheme to the page
 * @param {string} color - 'blue', 'green', 'purple', 'red', 'orange'
 */
function applyColorScheme(color) {
    const body = document.body;
    
    // Remove all color classes
    body.classList.remove('color-blue', 'color-green', 'color-purple', 'color-red', 'color-orange');
    
    // Add new color class
    body.classList.add(`color-${color}`);
    
    // Save to localStorage
    localStorage.setItem('colorScheme', color);
}

/**
 * Load saved theme and color scheme from localStorage
 */
function loadSavedTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    const savedColor = localStorage.getItem('colorScheme') || 'blue';
    
    applyTheme(savedTheme);
    applyColorScheme(savedColor);
}

/**
 * Initialize autocomplete for customer search
 */
function initCustomerSearch() {
    const searchInput = document.getElementById('customer_search');
    if (!searchInput) return;
    
    let searchTimeout;
    searchInput.addEventListener('input', function() {
        clearTimeout(searchTimeout);
        const query = this.value.trim();
        
        if (query.length < 2) {
            document.getElementById('customer_results').style.display = 'none';
            return;
        }
        
        searchTimeout = setTimeout(() => {
            fetch(`/customer/search?q=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(customers => {
                    const results = document.getElementById('customer_results');
                    results.innerHTML = '';
                    
                    customers.forEach(customer => {
                        const div = document.createElement('a');
                        div.href = '#';
                        div.className = 'list-group-item list-group-item-action';
                        div.textContent = `${customer.name} - ${customer.phone}`;
                        div.onclick = (e) => {
                            e.preventDefault();
                            selectCustomer(customer.id, customer.name);
                        };
                        results.appendChild(div);
                    });
                    
                    results.style.display = customers.length > 0 ? 'block' : 'none';
                })
                .catch(error => console.error('Error:', error));
        }, 300);
    });
}

/**
 * Select a customer from search results
 */
function selectCustomer(customerId, customerName) {
    document.getElementById('customer_id').value = customerId;
    document.getElementById('customer_search').value = customerName;
    document.getElementById('customer_results').style.display = 'none';
    document.getElementById('device_search').disabled = false;
    document.getElementById('new_device_btn').disabled = false;
    document.getElementById('modal_device_customer_id').value = customerId;
    document.getElementById('device_search').value = '';
    document.getElementById('device_results').innerHTML = '';
}

/**
 * Initialize autocomplete for device search
 */
function initDeviceSearch() {
    const searchInput = document.getElementById('device_search');
    if (!searchInput) return;
    
    let searchTimeout;
    searchInput.addEventListener('input', function() {
        clearTimeout(searchTimeout);
        const customerId = document.getElementById('customer_id').value;
        if (!customerId) return;
        
        const query = this.value.trim();
        
        searchTimeout = setTimeout(() => {
            fetch(`/device/search/${customerId}?q=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(devices => {
                    const results = document.getElementById('device_results');
                    results.innerHTML = '';
                    
                    devices.forEach(device => {
                        const div = document.createElement('a');
                        div.href = '#';
                        div.className = 'list-group-item list-group-item-action';
                        div.textContent = device.display;
                        div.onclick = (e) => {
                            e.preventDefault();
                            selectDevice(device.id, device.display);
                        };
                        results.appendChild(div);
                    });
                    
                    results.style.display = devices.length > 0 ? 'block' : 'none';
                })
                .catch(error => console.error('Error:', error));
        }, 300);
    });
}

/**
 * Select a device from search results
 */
function selectDevice(deviceId, deviceDisplay) {
    document.getElementById('device_id').value = deviceId;
    document.getElementById('device_search').value = deviceDisplay;
    document.getElementById('device_results').style.display = 'none';
}

/**
 * Initialize common problem quick-select buttons
 */
function initCommonProblems() {
    document.querySelectorAll('.problem-quick-select').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const textarea = document.getElementById('problem_description');
            if (textarea) {
                textarea.value = this.dataset.problem;
                textarea.focus();
            }
        });
    });
}

/**
 * Initialize new customer modal
 */
function initNewCustomerModal() {
    const saveBtn = document.getElementById('saveCustomerBtn');
    if (!saveBtn) return;
    
    saveBtn.addEventListener('click', async function() {
        const form = document.getElementById('newCustomerForm');
        const formData = new FormData(form);
        
        try {
            const response = await fetch('/customer/new', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                selectCustomer(data.id, data.name);
                const modal = bootstrap.Modal.getInstance(document.getElementById('newCustomerModal'));
                modal.hide();
                form.reset();
            } else {
                alert('Error creating customer');
            }
        } catch (error) {
            console.error('Error:', error);
        }
    });
}

/**
 * Initialize new device modal
 */
function initNewDeviceModal() {
    const saveBtn = document.getElementById('saveDeviceBtn');
    if (!saveBtn) return;
    
    saveBtn.addEventListener('click', async function() {
        const form = document.getElementById('newDeviceForm');
        const formData = new FormData(form);
        
        try {
            const response = await fetch('/device/new', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                selectDevice(data.id, data.display);
                const modal = bootstrap.Modal.getInstance(document.getElementById('newDeviceModal'));
                modal.hide();
                form.reset();
            } else {
                alert('Error creating device');
            }
        } catch (error) {
            console.error('Error:', error);
        }
    });
}

/**
 * Close dropdown menus when clicking outside
 */
function initDropdownCloseOnClickOutside() {
    document.addEventListener('click', function(event) {
        const searchResults = document.getElementById('customer_results');
        const deviceResults = document.getElementById('device_results');
        
        if (searchResults && !searchResults.contains(event.target) && event.target.id !== 'customer_search') {
            searchResults.style.display = 'none';
        }
        
        if (deviceResults && !deviceResults.contains(event.target) && event.target.id !== 'device_search') {
            deviceResults.style.display = 'none';
        }
    });
}

/**
 * Format time to 24-hour format
 */
function formatTime(date) {
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${hours}:${minutes}`;
}

/**
 * Initialize all JavaScript on page load
 */
document.addEventListener('DOMContentLoaded', function() {
    // Load saved theme
    loadSavedTheme();
    
    // Initialize autocomplete
    initCustomerSearch();
    initDeviceSearch();
    initCommonProblems();
    initNewCustomerModal();
    initNewDeviceModal();
    initDropdownCloseOnClickOutside();
    
    // Add smooth transitions
    document.querySelectorAll('a, button').forEach(element => {
        element.addEventListener('click', function() {
            if (!this.classList.contains('no-smooth')) {
                this.style.transition = 'all 0.2s ease';
            }
        });
    });
});

/**
 * Utility: Format currency
 */
function formatCurrency(amount) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(amount);
}

/**
 * Utility: Format date
 */
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
    });
}

/**
 * Utility: Confirm deletion
 */
function confirmDelete(message = 'Are you sure you want to delete this item?') {
    return confirm(message);
}

// Export functions for global use
window.applyTheme = applyTheme;
window.applyColorScheme = applyColorScheme;
window.selectCustomer = selectCustomer;
window.selectDevice = selectDevice;
window.formatCurrency = formatCurrency;
window.formatDate = formatDate;
window.confirmDelete = confirmDelete;