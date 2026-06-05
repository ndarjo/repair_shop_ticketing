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
 * Initialize theme and color scheme.
 * Prioritizes server-side attributes, falls back to localStorage.
 */
function initializeTheme() {
    const body = document.body;
    const serverTheme = body.getAttribute('data-theme-pref');
    const serverColor = body.getAttribute('data-color-pref');

    // Priority: Server attributes > LocalStorage > Defaults
    const theme = serverTheme || localStorage.getItem('theme') || 'light';
    const color = serverColor || localStorage.getItem('colorScheme') || 'blue';

    applyTheme(theme);
    applyColorScheme(color);

    // Ensure localStorage is synced for anonymous sessions
    if (!serverTheme) localStorage.setItem('theme', theme);
    if (!serverColor) localStorage.setItem('colorScheme', color);
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
        
        const results = document.getElementById('customer_results');
        results.innerHTML = '<div class="list-group-item text-muted"><i class="fas fa-spinner fa-spin me-2"></i>Searching...</div>';
        results.style.display = 'block';

        searchTimeout = setTimeout(() => {
            fetch(`/customer/search?q=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(customers => {
                    results.innerHTML = '';
                    
                    if (customers.length === 0) {
                        results.innerHTML = '<div class="list-group-item text-muted">No customers found. Click "Create New" to add one.</div>';
                    }

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
                    
                })
                .catch(error => console.error('Error:', error));
        }, 300);
    });
}

/**
 * Select a customer from search results
 */
function selectCustomer(customerId, customerName) {
    const customerInput = document.getElementById('customer_search');
    const deviceInput = document.getElementById('device_search');

    document.getElementById('customer_id').value = customerId;
    customerInput.value = customerName;
    customerInput.classList.add('is-valid'); // Visual polish: green highlight on selection
    
    document.getElementById('customer_results').style.display = 'none';
    deviceInput.disabled = false;
    document.getElementById('new_device_btn').disabled = false;
    document.getElementById('modal_device_customer_id').value = customerId;
    deviceInput.value = '';
    document.getElementById('device_results').innerHTML = '';
    
    // Mobile navigation: hide keyboard before moving to next field
    customerInput.blur();
    setTimeout(() => {
        deviceInput.focus();
    }, 100);
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
        
        const results = document.getElementById('device_results');
        results.innerHTML = '<div class="list-group-item text-muted"><i class="fas fa-spinner fa-spin me-2"></i>Searching...</div>';
        results.style.display = 'block';

        searchTimeout = setTimeout(() => {
            fetch(`/device/search/${customerId}?q=${encodeURIComponent(query)}`)
                .then(response => response.json())
                .then(devices => {
                    results.innerHTML = '';
                    
                    if (devices.length === 0) {
                        results.innerHTML = '<div class="list-group-item text-muted">No devices found for this customer.</div>';
                    }

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
                    
                })
                .catch(error => console.error('Error:', error));
        }, 300);
    });
}

/**
 * Select a device from search results
 */
function selectDevice(deviceId, deviceDisplay) {
    const deviceInput = document.getElementById('device_search');
    document.getElementById('device_id').value = deviceId;
    deviceInput.value = deviceDisplay;
    deviceInput.classList.add('is-valid'); // Visual polish
    document.getElementById('device_results').style.display = 'none';
    deviceInput.blur(); // Hide keyboard on mobile
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
                const existingText = textarea.value.trim();
                const newProblem = this.dataset.problem;
                textarea.value = existingText ? `${existingText}, ${newProblem}` : newProblem;
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
    
    const originalText = saveBtn.innerHTML;

    saveBtn.addEventListener('click', async function() {
        const form = document.getElementById('newCustomerForm');
        const formData = new FormData(form);
        
        try {
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';

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
                
                // Hide modal first to clear the backdrop
                const modalElement = document.getElementById('newCustomerModal');
                bootstrap.Modal.getInstance(modalElement)?.hide();
                
                selectCustomer(data.id, data.name);
                form.reset();
            } else {
                const errorData = await response.json();
                alert(`Error creating customer: ${errorData.error || response.statusText}`);
            }
        } catch (error) {
            console.error('Error:', error);
        } finally {
            saveBtn.disabled = false;
            saveBtn.innerHTML = originalText;
        }
    });
}

/**
 * Initialize new device modal
 */
function initNewDeviceModal() {
    const saveBtn = document.getElementById('saveDeviceBtn');
    if (!saveBtn) return;
    
    const originalText = saveBtn.innerHTML;

    saveBtn.addEventListener('click', async function() {
        const form = document.getElementById('newDeviceForm');
        const formData = new FormData(form);
        
        try {
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';

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
                
                // Hide modal first to clear the backdrop
                const modalElement = document.getElementById('newDeviceModal');
                bootstrap.Modal.getInstance(modalElement)?.hide();
                
                selectDevice(data.id, data.display);
                form.reset();
            } else {
                const errorData = await response.json();
                alert(`Error creating device: ${errorData.error || response.statusText}`);
            }
        } catch (error) {
            console.error('Error:', error);
        } finally {
            saveBtn.disabled = false;
            saveBtn.innerHTML = originalText;
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
        if (control.tagName === 'INPUT' && control.type === 'radio') {
            control.addEventListener('change', function() {
                if (this.checked) applyColorScheme(this.value);
            });
        } else {
            control.addEventListener('click', function(e) {
                e.preventDefault();
                applyColorScheme(this.dataset.colorControl);
            });
        }
    });
}

/**
 * Initialize Ticket Detail Calculator and UI Logic
 */
function initTicketDetail() {
    const paymentAmountInput = document.getElementById('paymentAmount');
    if (!paymentAmountInput) return;

    const cashReceivedInput = document.getElementById('cashReceived');
    const changeToGiveDisplay = document.getElementById('changeToGive');
    const fillBalanceBtn = document.getElementById('fillBalanceBtn');
    
    const currentBalance = parseFloat(paymentAmountInput.dataset.balance || 0);
    const decimals = parseInt(paymentAmountInput.dataset.decimals || 2);

    if (fillBalanceBtn) {
        fillBalanceBtn.addEventListener('click', () => {
            paymentAmountInput.value = currentBalance.toFixed(decimals);
            updateChange();
        });
    }

    function updateChange() {
        const amount = parseFloat(paymentAmountInput.value) || 0;
        const received = parseFloat(cashReceivedInput.value) || 0;
        const change = received - amount;
        
        changeToGiveDisplay.textContent = (change >= 0 ? change : 0).toFixed(decimals);

        // Add visual feedback: green text if change is due
        if (change > 0) {
            changeToGiveDisplay.classList.add('text-success', 'fw-bold');
        } else {
            changeToGiveDisplay.classList.remove('text-success', 'fw-bold');
        }
    }

    paymentAmountInput.addEventListener('input', updateChange);
    cashReceivedInput.addEventListener('input', updateChange);
}

/**
 * Toggle Part Price and Manual Name fields based on inventory selection
 */
function initPartModalLogic() {
    const partSelect = document.getElementById('partSelect');
    const manualName = document.getElementById('manualPartName');
    const partPrice = document.getElementById('partPrice');
    const partCost = document.getElementById('partCost');

    if (!partSelect || !manualName || !partPrice || !partCost) return;

    function toggleFields() {
        const isInventorySelected = partSelect.value !== "";
        
        if (isInventorySelected) {
            manualName.value = "";
            manualName.disabled = true;
            partPrice.value = ""; // Clear to let server use catalog price
            partPrice.disabled = true;
            partPrice.placeholder = "Using catalog price...";
            partCost.value = "";
            partCost.disabled = true;
            partCost.placeholder = "Using catalog cost...";
        } else {
            manualName.disabled = false;
            partPrice.disabled = false;
            partPrice.placeholder = (0).toFixed(parseInt(partPrice.step.includes('.') ? partPrice.step.split('.')[1].length : 0));
            partCost.disabled = false;
            partCost.placeholder = (0).toFixed(parseInt(partCost.step.includes('.') ? partCost.step.split('.')[1].length : 0));
        }
    }

    partSelect.addEventListener('change', toggleFields);
}

/**
 * Initialize dynamic modals for inventory and services
 * This prevents DOM bloating by using a single modal for all items
 */
function initDynamicAdminModals() {
    // Handle Parts Edit Modal
    const editPartModal = document.getElementById('editPartModal');
    if (editPartModal) {
        document.querySelectorAll('.edit-part-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const data = this.dataset;
                document.getElementById('editPartForm').action = `/inventory/edit/${data.id}`;
                document.getElementById('edit_part_name').value = data.name;
                document.getElementById('edit_part_cost').value = data.cost;
                document.getElementById('edit_part_price').value = data.price;
                document.getElementById('edit_part_stock').value = data.stock;
                document.getElementById('edit_part_active').checked = data.active === 'true';
            });
        });
    }

    // Handle Services Edit Modal
    const editServiceModal = document.getElementById('editServiceModal');
    if (editServiceModal) {
        document.querySelectorAll('.edit-service-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                const data = this.dataset;
                document.getElementById('editServiceForm').action = `/services/edit/${data.id}`;
                document.getElementById('edit_service_name').value = data.name;
                document.getElementById('edit_service_description').value = data.description;
                document.getElementById('edit_service_price').value = data.price;
                document.getElementById('edit_service_active').checked = data.active === 'true';
            });
        });
    }
}

/**
 * Initialize generic reload button handler
 */
function initReloadHandler() {
    const btn = document.getElementById('reloadPageBtn');
    if (btn) {
        btn.addEventListener('click', () => window.location.reload());
    }
}

/**
 * Initialize generic print button handler
 */
function initPrintHandler() {
    const btn = document.getElementById('printInvoiceBtn');
    if (btn) {
        btn.addEventListener('click', () => window.print());
    }
}

/**
 * Initialize form auto-submit for marked elements
 */
function initFormAutoSubmit() {
    document.querySelectorAll('.auto-submit').forEach(el => {
        el.addEventListener('change', function() {
            this.form.submit();
        });
    });
}

/**
 * Initialize global confirmation dialogs for forms and buttons
 */
function initGlobalConfirmations() {
    // For forms
    document.querySelectorAll('form.confirm-action').forEach(form => {
        form.addEventListener('submit', function(e) {
            const msg = this.dataset.confirm || 'Are you sure?';
            if (!confirm(msg)) e.preventDefault();
        });
    });
    // For individual buttons/links
    document.querySelectorAll('.confirm-action:not(form)').forEach(el => {
        el.addEventListener('click', function(e) {
            const msg = this.dataset.confirm || 'Are you sure?';
            if (!confirm(msg)) e.preventDefault();
        });
    });
}

/**
 * Initialize Financial Analytics Chart
 */
function initFinanceChart() {
    const canvas = document.getElementById('financeChart');
    if (!canvas || typeof Chart === 'undefined') return;

    const theme = document.documentElement.dataset.theme || 'light';
    const isDark = theme === 'dark';
    const textColor = isDark ? '#e0e0e0' : '#212529';
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';

    // Extract primary color based on active color scheme class
    let primaryColor = '#0d6efd';
    const body = document.body;
    if (body.classList.contains('color-green')) primaryColor = '#198754';
    else if (body.classList.contains('color-purple')) primaryColor = '#6f42c1';
    else if (body.classList.contains('color-red')) primaryColor = '#dc3545';
    else if (body.classList.contains('color-orange')) primaryColor = '#fd7e14';

    const labels = JSON.parse(canvas.dataset.labels);
    const revenue = JSON.parse(canvas.dataset.revenue);
    const costs = JSON.parse(canvas.dataset.costs);
    const profit = JSON.parse(canvas.dataset.profit);

    new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Net Profit',
                    data: profit,
                    backgroundColor: primaryColor,
                    borderRadius: 4,
                    order: 1
                },
                {
                    type: 'bar',
                    label: 'Gross Revenue',
                    data: revenue,
                    backgroundColor: isDark ? '#1a6b3d' : '#198754',
                    borderRadius: 4,
                    order: 2
                },
                {
                    type: 'bar',
                    label: 'Hardware Costs',
                    data: costs,
                    backgroundColor: isDark ? '#842029' : '#dc3545',
                    borderRadius: 4,
                    order: 3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'index' },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: gridColor },
                    ticks: { color: textColor }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: textColor }
                }
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { color: textColor, usePointStyle: true, padding: 20 }
                },
                tooltip: {
                    padding: 12,
                    backgroundColor: isDark ? '#2d2d2d' : '#ffffff',
                    titleColor: isDark ? '#ffffff' : '#212529',
                    bodyColor: isDark ? '#e0e0e0' : '#212529',
                    borderColor: gridColor,
                    borderWidth: 1
                }
            }
        }
    });
}

// ========================================
// CORE ENGINE INITIALIZATION
// ========================================
document.addEventListener('DOMContentLoaded', () => {
    initializeTheme();
    initThemeToggles();
    initCustomerSearch();
    initDeviceSearch();
    initCommonProblems();
    initNewCustomerModal();
    initNewDeviceModal();
    initTicketDetail();
    initFinanceChart();
    initPartModalLogic();
    initDynamicAdminModals();
    initReloadHandler();
    initPrintHandler();
    initFormAutoSubmit();
    initGlobalConfirmations();

    // UI POLISH: Close autocomplete dropdowns when clicking outside the component
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
