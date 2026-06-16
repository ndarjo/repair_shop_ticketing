/**
 * Ticket Search & Intake Module
 * Handles AJAX searching for customers/devices and modal registration.
 */

// Integrity: Global helper to filter out technical null artifacts and trim whitespace
const getVal = (v) => (v && v !== 'None') ? v.trim() : '';

document.addEventListener('DOMContentLoaded', function() {
    initCustomerSearch();
    initDeviceSearch();
    initNewCustomerModal();
    initNewDeviceModal();

    // UI Integrity: Close autocomplete dropdowns when clicking outside
    document.addEventListener('click', function(e) {
        const customerResults = document.getElementById('customer_results');
        const deviceResults = document.getElementById('device_results');
        
        if (customerResults && !e.target.closest('#customer_search') && !e.target.closest('#customer_results')) {
            customerResults.style.display = 'none';
        }
        if (deviceResults && !e.target.closest('#device_search') && !e.target.closest('#device_results')) {
            deviceResults.style.display = 'none';
        }
    });
});

function initCustomerSearch() {
    const searchInput = document.getElementById('customer_search');
    if (!searchInput) return;
    
    let searchTimeout;
    let lastFetchId = 0;

    searchInput.addEventListener('input', function() {
        clearTimeout(searchTimeout);
        const query = getVal(this.value);

        // Integrity: Reset selection when user types to prevent accidental ID mismatch
        const customerIdInput = document.getElementById('customer_id');
        if (customerIdInput) customerIdInput.value = '';

        const deviceIdInput = document.getElementById('device_id');
        if (deviceIdInput) deviceIdInput.value = '';

        const modalCustId = document.getElementById('modal_device_customer_id');
        if (modalCustId) modalCustId.value = '';

        this.classList.remove('is-valid');
        const deviceInput = document.getElementById('device_search');
        const deviceResults = document.getElementById('device_results');
        const newDeviceBtn = document.getElementById('new_device_btn');
        
        if (deviceInput) {
            deviceInput.classList.remove('is-valid');
            deviceInput.disabled = true;
            deviceInput.value = '';
        }
        if (deviceResults) {
            deviceResults.innerHTML = '';
            deviceResults.style.display = 'none';
        }
        if (newDeviceBtn) newDeviceBtn.disabled = true;
        
        const results = document.getElementById('customer_results');
        if (query.length < 2) {
            if (results) {
                results.innerHTML = '';
                results.style.display = 'none';
            }
            return;
        }
        
        if (results) {
            const searchingText = getVal(searchInput.getAttribute('data-searching-text')) || 'Searching...';
            results.innerHTML = `<div class="list-group-item text-muted"><i class="fas fa-spinner fa-spin me-2"></i>${searchingText}</div>`;
            results.style.display = 'block';
        }

        const fetchId = ++lastFetchId;
        searchTimeout = setTimeout(() => {
            fetch(`/customer/search?q=${encodeURIComponent(query)}`)
                .then(response => {
                    if (!response.ok) throw new Error('Search failed');
                    return response.json();
                })
                .then(customers => {
                    if (!results || fetchId !== lastFetchId) return;
                    results.innerHTML = '';
                    
                    if (customers.length === 0) {
                        const noResultsText = getVal(searchInput.getAttribute('data-no-results-text')) || 'No customers found.';
                        results.innerHTML = `<div class="list-group-item text-muted">${noResultsText}</div>`;
                    }

                    customers.forEach(customer => {
                        const div = document.createElement('a');
                        div.href = '#';
                        div.className = 'list-group-item list-group-item-action';
                        div.textContent = `${customer.name || ''} - ${customer.phone || ''}`;
                        div.addEventListener('click', function(e) {
                            e.preventDefault();
                            selectCustomer(customer.id, customer.name);
                        });
                        results.appendChild(div);
                    });
                })
                .catch(error => {
                    console.error('Error:', error);
                    const errorText = getVal(searchInput.getAttribute('data-error-text')) || 'Search failed.';
                    if (results) results.innerHTML = `<div class="list-group-item text-danger">${errorText}</div>`;
                });
        }, 300);
    });
}

function selectCustomer(customerId, customerName) {
    const customerInput = document.getElementById('customer_search');
    const deviceInput = document.getElementById('device_search');
    const customerIdInput = document.getElementById('customer_id');
    const deviceIdInput = document.getElementById('device_id');
    const newDeviceBtn = document.getElementById('new_device_btn');
    const modalCustId = document.getElementById('modal_device_customer_id');

    if (customerIdInput) customerIdInput.value = customerId;
    if (deviceIdInput) deviceIdInput.value = '';
    
    if (customerInput) {
        customerInput.value = customerName || '';
        customerInput.classList.add('is-valid');
    }
    
    const customerResults = document.getElementById('customer_results');
    if (customerResults) customerResults.style.display = 'none';

    const deviceResults = document.getElementById('device_results');
    if (deviceResults) {
        deviceResults.innerHTML = '';
        deviceResults.style.display = 'none';
    }

    if (deviceInput) {
        deviceInput.disabled = false;
        deviceInput.value = '';
        deviceInput.classList.remove('is-valid');
        
        // UX: Automatically trigger device search for the selected customer
        deviceInput.dispatchEvent(new Event('input'));
        
        setTimeout(() => deviceInput.focus(), 100);
    }
    
    if (newDeviceBtn) newDeviceBtn.disabled = false;
    if (modalCustId) modalCustId.value = customerId;
}

function initDeviceSearch() {
    const searchInput = document.getElementById('device_search');
    if (!searchInput) return;
    
    let searchTimeout;
    let lastFetchId = 0;

    const performDeviceSearch = function() {
        clearTimeout(searchTimeout);

        // Integrity: Reset selection when user types
        const deviceIdInput = document.getElementById('device_id');
        if (deviceIdInput) deviceIdInput.value = '';
        this.classList.remove('is-valid');

        const customerIdInput = document.getElementById('customer_id');
        const customerId = customerIdInput ? getVal(customerIdInput.value) : '';
        if (!customerId) return;
        
        const query = getVal(this.value);
        const results = document.getElementById('device_results');

        if (results) {
            const searchingText = getVal(searchInput.getAttribute('data-searching-text')) || 'Searching...';
            results.innerHTML = `<div class="list-group-item text-muted"><i class="fas fa-spinner fa-spin me-2"></i>${searchingText}</div>`;
            results.style.display = 'block';
        }

        const fetchId = ++lastFetchId;
        searchTimeout = setTimeout(() => {
            fetch(`/device/search/${customerId}?q=${encodeURIComponent(query)}`)
                .then(response => {
                    if (!response.ok) throw new Error('Search failed');
                    return response.json();
                })
                .then(devices => {
                    if (!results || fetchId !== lastFetchId) return;
                    results.innerHTML = '';
                    
                    if (devices.length === 0) {
                        const currentQuery = getVal(searchInput.value);
                        const noResultsText = getVal(searchInput.getAttribute('data-no-results-text')) || 'No devices found.';
                        const noDevicesText = getVal(searchInput.getAttribute('data-no-devices-registered-text')) || 'No devices registered for this customer.';
                        
                        // If query is empty, it means the customer has zero devices in the database
                        const msg = currentQuery === '' ? noDevicesText : noResultsText;
                        results.innerHTML = `<div class="list-group-item text-warning fw-bold"><i class="fas fa-exclamation-triangle me-2"></i>${msg}</div>`;
                    }

                    devices.forEach(device => {
                        const div = document.createElement('a');
                        div.href = '#';
                        div.className = 'list-group-item list-group-item-action';
                        div.textContent = device.display || '';
                        div.addEventListener('click', function(e) {
                            e.preventDefault();
                            selectDevice(device.id, device.display);
                        });
                        results.appendChild(div);
                    });
                })
                .catch(error => {
                    console.error('Error:', error);
                    const errorText = getVal(searchInput.getAttribute('data-error-text')) || 'Search failed.';
                    if (results) results.innerHTML = `<div class="list-group-item text-danger">${errorText}</div>`;
                });
        }, 300);
    };

    searchInput.addEventListener('input', performDeviceSearch);
    searchInput.addEventListener('focus', performDeviceSearch);
}

function selectDevice(deviceId, deviceDisplay) {
    const deviceInput = document.getElementById('device_search');
    const deviceIdInput = document.getElementById('device_id');
    if (deviceIdInput) deviceIdInput.value = deviceId;
    if (deviceInput) {
        deviceInput.value = deviceDisplay || '';
        deviceInput.classList.add('is-valid');
        deviceInput.blur();
    }
    const deviceResults = document.getElementById('device_results');
    if (deviceResults) {
        deviceResults.innerHTML = '';
        deviceResults.style.display = 'none';
    }
}

/**
 * Shared AJAX utility to handle modal form submissions (Customer/Device)
 */
window.handleModalSubmit = function(form, btn, url, successCallback) {
    const formData = new FormData(form);
    const originalText = btn.innerHTML;
    
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i> ' + (btn.getAttribute('data-loading-text') || 'Saving...');

    fetch(url, {
        method: 'POST',
        body: formData,
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            alert(data.error);
            btn.disabled = false;
            btn.innerHTML = originalText;
        } else {
            // Success: Clean up modal and update the main ticket intake form
            const modalEl = form.closest('.modal');
            const modalInstance = bootstrap.Modal.getInstance(modalEl);
            if (modalInstance) modalInstance.hide();
            
            form.reset();
            btn.disabled = false;
            btn.innerHTML = originalText;
            
            if (successCallback) successCallback(data.id, data.name || data.display);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An unexpected error occurred. Please try again.');
        btn.disabled = false;
        btn.innerHTML = originalText;
    });
};

function initNewCustomerModal() {
    const form = document.getElementById('newCustomerForm');
    const saveBtn = document.getElementById('saveCustomerBtn');
    if (!form || !saveBtn) return;

    saveBtn.addEventListener('click', () => form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true })));

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        if (typeof window.handleModalSubmit === 'function') {
            window.handleModalSubmit(form, saveBtn, '/customer/new', selectCustomer);
        }
    });
}

function initNewDeviceModal() {
    const form = document.getElementById('newDeviceForm');
    const saveBtn = document.getElementById('saveDeviceBtn');
    if (!form || !saveBtn) return;

    saveBtn.addEventListener('click', () => form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true })));

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        if (typeof window.handleModalSubmit === 'function') {
            window.handleModalSubmit(form, saveBtn, '/device/new', selectDevice);
        }
    });
}