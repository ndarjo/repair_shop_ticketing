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
 * Retrieves the CSRF token from a meta tag in the HTML.
 * Assumes the token is available in <meta name="csrf-token" content="...">
 * @returns {string} The CSRF token, or an empty string if not found.
 */
function getCsrfToken() {
    const tokenMeta = document.querySelector('meta[name="csrf-token"]');
    if (tokenMeta) {
        return tokenMeta.getAttribute('content');
    }
    console.warn("CSRF token meta tag not found. AJAX POST requests might fail.");
    return '';
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
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCsrfToken() // Add CSRF token for security
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                // Assuming selectCustomer handles UI updates for success
                selectCustomer(data.id, data.name);
                const modalElement = document.getElementById('newCustomerModal');
                const modal = bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
                modal.hide();
                form.reset();
            } else {
                alert('Error creating customer');
                const errorData = await response.json();
                alert(`Error creating customer: ${errorData.error || response.statusText}`);
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
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCsrfToken() // Add CSRF token for security
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                // Assuming selectDevice handles UI updates for success
                selectDevice(data.id, data.display);
                const modalElement = document.getElementById('newDeviceModal');
                const modal = bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
                modal.hide();
                form.reset();
            } else {
                alert('Error creating device');
                const errorData = await response.json();
                alert(`Error creating device: ${errorData.error || response.statusText}`);
            }
        } catch (error) {
            console.error('Error:', error);
        }
    });
}

/**
 * Bind Theme Toggle inputs if present in the layout DOM
 */
function initThemeToggles() {
    document.querySelectorAll('[data-theme-control]').forEach(control => {
        control.addEventListener('change', function() {
            applyTheme(this.value);
        });
    });
    
    document.querySelectorAll('[data-color-control]').forEach(control => {
        control.addEventListener('click', function(e) {
            e.preventDefault();
            applyColorScheme(this.dataset.colorControl);
        });
    });
}

// ========================================
// CORE ENGINE INITIALIZATION
// ========================================
document.addEventListener('DOMContentLoaded', () => {
    loadSavedTheme();
    initThemeToggles();
    initCustomerSearch();
    initDeviceSearch();
    initCommonProblems();
    initNewCustomerModal();
    initNewDeviceModal();
});
