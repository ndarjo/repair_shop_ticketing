/**
 * Ticket Search & Intake Module
 * Handles AJAX searching for customers/devices and modal registration.
 */

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
        const query = this.value.trim();

        // Integrity: Reset selection when user types to prevent accidental ID mismatch
        const customerIdInput = document.getElementById('customer_id');
        if (customerIdInput) customerIdInput.value = '';

        const deviceIdInput = document.getElementById('device_id');
        if (deviceIdInput) deviceIdInput.value = '';

        this.classList.remove('is-valid');
        const deviceInput = document.getElementById('device_search');
        const newDeviceBtn = document.getElementById('new_device_btn');
        
        if (deviceInput) {
            deviceInput.classList.remove('is-valid');
            deviceInput.disabled = true;
            deviceInput.value = '';
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
            results.innerHTML = '<div class="list-group-item text-muted"><i class="fas fa-spinner fa-spin me-2"></i>Searching...</div>';
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
                        results.innerHTML = '<div class="list-group-item text-muted">No customers found.</div>';
                    }

                    customers.forEach(customer => {
                        const div = document.createElement('a');
                        div.href = '#';
                        div.className = 'list-group-item list-group-item-action';
                        div.textContent = `${customer.name} - ${customer.phone}`;
                        div.addEventListener('click', function(e) {
                            e.preventDefault();
                            selectCustomer(customer.id, customer.name);
                        });
                        results.appendChild(div);
                    });
                })
                .catch(error => {
                    console.error('Error:', error);
                    if (results) results.innerHTML = '<div class="list-group-item text-danger">Search failed.</div>';
                });
        }, 300);
    });
}

function selectCustomer(customerId, customerName) {
    const customerInput = document.getElementById('customer_search');
    const deviceInput = document.getElementById('device_search');
    const customerIdInput = document.getElementById('customer_id');
    const newDeviceBtn = document.getElementById('new_device_btn');
    const modalCustId = document.getElementById('modal_device_customer_id');

    if (customerIdInput) customerIdInput.value = customerId;
    if (customerInput) {
        customerInput.value = customerName;
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

    searchInput.addEventListener('input', function() {
        clearTimeout(searchTimeout);
        const customerIdInput = document.getElementById('customer_id');
        if (!customerIdInput || !customerIdInput.value) return;
        
        const query = this.value.trim();
        const customerId = customerIdInput.value;
        const results = document.getElementById('device_results');

        if (query.length < 1) {
            if (results) {
                results.innerHTML = '';
                results.style.display = 'none';
            }
            return;
        }

        const deviceIdInput = document.getElementById('device_id');
        if (deviceIdInput) deviceIdInput.value = '';
        this.classList.remove('is-valid');
        
        if (results) {
            results.innerHTML = '<div class="list-group-item text-muted"><i class="fas fa-spinner fa-spin me-2"></i>Searching...</div>';
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
                        results.innerHTML = '<div class="list-group-item text-muted">No devices found.</div>';
                    }

                    devices.forEach(device => {
                        const div = document.createElement('a');
                        div.href = '#';
                        div.className = 'list-group-item list-group-item-action';
                        div.textContent = device.display;
                        div.addEventListener('click', function(e) {
                            e.preventDefault();
                            selectDevice(device.id, device.display);
                        });
                        results.appendChild(div);
                    });
                })
                .catch(error => {
                    console.error('Error:', error);
                    if (results) results.innerHTML = '<div class="list-group-item text-danger">Search failed.</div>';
                });
        }, 300);
    });
}

function selectDevice(deviceId, deviceDisplay) {
    const deviceInput = document.getElementById('device_search');
    const deviceIdInput = document.getElementById('device_id');
    if (deviceIdInput) deviceIdInput.value = deviceId;
    if (deviceInput) {
        deviceInput.value = deviceDisplay;
        deviceInput.classList.add('is-valid');
        deviceInput.blur();
    }
    const deviceResults = document.getElementById('device_results');
    if (deviceResults) {
        deviceResults.innerHTML = '';
        deviceResults.style.display = 'none';
    }
}

function initNewCustomerModal() {
    const saveBtn = document.getElementById('saveCustomerBtn');
    if (!saveBtn) return;
    saveBtn.addEventListener('click', function() {
        const form = document.getElementById('newCustomerForm');
        if (!form) return;
        // The actual fetch logic is shared in main.js to keep search.js clean
        if (typeof window.handleModalSubmit === 'function') {
            window.handleModalSubmit(form, saveBtn, '/customer/new', selectCustomer);
        }
    });
}

function initNewDeviceModal() {
    const saveBtn = document.getElementById('saveDeviceBtn');
    if (!saveBtn) return;
    saveBtn.addEventListener('click', function() {
        const form = document.getElementById('newDeviceForm');
        if (!form) return;
        if (typeof window.handleModalSubmit === 'function') {
            window.handleModalSubmit(form, saveBtn, '/device/new', selectDevice);
        }
    });
}