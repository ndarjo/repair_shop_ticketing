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
    
    // Integrity: Fallback for invalid or nullish values
    if (!theme || theme === 'None' || theme === 'undefined') {
        theme = 'light';
    }

    let displayTheme = theme;
    if (theme === 'system') {
        displayTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    // Update data attribute
    if (html.dataset.theme !== displayTheme) html.dataset.theme = displayTheme;
    
    // Update body class
    const themeClass = `theme-${displayTheme}`;
    if (!body.classList.contains(themeClass)) {
        body.classList.remove('theme-light', 'theme-dark', 'theme-system');
        if (displayTheme) body.classList.add(themeClass);
    }
    
    // Save to localStorage
    try {
        localStorage.setItem('theme', theme);
    } catch (e) {
        // Storage unavailable or disabled
    }
}

/**
 * Apply color scheme to the page
 * @param {string} color - 'blue', 'green', 'purple', 'red', 'orange'
 */
function applyColorScheme(color) {
    const body = document.body;
    
    // Integrity: Fallback for invalid or nullish values
    if (!color || color === 'None' || color === 'undefined') {
        color = 'blue';
    }

    const colorClass = `color-${color}`;
    if (body.classList.contains(colorClass)) return;

    // Remove all color classes
    body.classList.remove('color-blue', 'color-green', 'color-purple', 'color-red', 'color-orange');
    
    // Add new color class
    if (color) body.classList.add(colorClass);
    
    // Save to localStorage
    try {
        localStorage.setItem('colorScheme', color);
    } catch (e) {
        // Storage unavailable or disabled
    }
}

/**
 * Initialize theme and color scheme.
 * Prioritizes server-side attributes, falls back to localStorage.
 */
function initializeTheme() {
    const body = document.body;
    
    // Helper to handle technical null representations
    const getAttr = (attr) => {
        const val = body.getAttribute(attr);
        return (val && val !== 'None') ? val : null;
    };

    const serverTheme = getAttr('data-theme-pref');
    const serverColor = getAttr('data-color-pref');

    let theme = serverTheme || 'light';
    let color = serverColor || 'blue';

    // Priority: Server attributes > LocalStorage > Defaults
    try {
        if (!serverTheme) {
            theme = localStorage.getItem('theme') || 'light';
        }
        if (!serverColor) {
            color = localStorage.getItem('colorScheme') || 'blue';
        }
    } catch (e) {
        // Use defaults if storage is restricted
    }

    applyTheme(theme);
    applyColorScheme(color);
}

/**
 * Shared AJAX Modal Submitter
 * Used by search.js to handle registration logic.
 */
window.handleModalSubmit = async function(form, btn, url, successCallback) {
    const formData = new FormData(form);
    const originalText = btn.innerHTML;
    
    // Helper to handle technical null representations
    const getAttr = (el, attr, def) => {
        const val = el.getAttribute(attr);
        return (val && val !== 'None') ? val : def;
    };

    try {
        // Localization: Support localized loading text via data attribute
        const loadingText = getAttr(btn, 'data-loading-text', 'Saving...');
        
        btn.disabled = true;
        btn.innerHTML = `<span class="spinner-border spinner-border-sm me-2"></span>${loadingText}`;

        const response = await fetch(url, {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': getCsrfToken()
            }
        });
        
        if (response.ok) {
            const data = await response.json().catch(() => ({}));
            const modalEl = form.closest('.modal');
            // Integrity: Ensure Bootstrap is available and use standard instance management
            if (modalEl && typeof bootstrap !== 'undefined' && bootstrap.Modal) {
                const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
                if (modal) modal.hide();
            }
            
            if (data && data.id && typeof successCallback === 'function') {
                // Integrity mapping: Support various model identifiers for successful AJAX registration
                const displayName = data.name || 
                                  data.display || 
                                  data.full_name || 
                                  data.username;
                successCallback(data.id, displayName || '');
            }
            form.reset();
        } else {
            const errorData = await response.json().catch(() => ({}));
            const fallbackError = getAttr(btn, 'data-error-msg', 'Operation failed');
            const errorLabel = getAttr(document.body, 'data-error-label', 'Error');
            alert(`${errorLabel}: ${errorData.error || response.statusText || fallbackError}`);
        }
    } catch (error) {
        console.error('Error:', error);
        const networkError = getAttr(btn, 'data-network-error', 'A network or server error occurred. Please try again.');
        alert(networkError);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
};

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
 * Bind Theme Toggle inputs if present in the layout DOM
 */
function initThemeToggles() {
    document.body.addEventListener('change', function(e) {
        const themeControl = e.target.closest('[data-theme-control]');
        if (themeControl) {
            applyTheme(themeControl.value);
        }
        
        const colorControl = e.target.closest('[data-color-control]');
        if (colorControl && colorControl.tagName === 'INPUT' && colorControl.type === 'radio') {
            if (colorControl.checked) applyColorScheme(colorControl.value);
        }
    });

    document.body.addEventListener('click', function(e) {
        const colorControl = e.target.closest('[data-color-control]');
        if (colorControl && colorControl.dataset.colorControl && !(colorControl.tagName === 'INPUT' && colorControl.type === 'radio')) {
            e.preventDefault();
            applyColorScheme(colorControl.dataset.colorControl);
        }
    });
}

/**
 * Initialize dynamic modals for inventory and services
 * This prevents DOM bloating by using a single modal for all items
 */
function initDynamicAdminModals() {
    // Helper to handle technical null representations from server attributes
    const getVal = (v) => (v && v !== 'None') ? v : '';
    // Robust boolean parsing for data attributes
    const getBool = (v) => v && String(v).toLowerCase() === 'true';

    document.body.addEventListener('click', function(e) {
        const partBtn = e.target.closest('.edit-part-btn');
        if (partBtn && partBtn.dataset.id && partBtn.dataset.id !== 'None') {
            const data = partBtn.dataset;
            const form = document.getElementById('editPartForm');
            if (form) {
                form.action = `/inventory/edit/${data.id}`;
                if (document.getElementById('edit_part_name')) document.getElementById('edit_part_name').value = getVal(data.name);
                if (document.getElementById('edit_part_cost')) document.getElementById('edit_part_cost').value = getVal(data.cost);
                if (document.getElementById('edit_part_price')) document.getElementById('edit_part_price').value = getVal(data.price);
                if (document.getElementById('edit_part_stock')) document.getElementById('edit_part_stock').value = getVal(data.stock) || '0';
                if (document.getElementById('edit_part_active')) document.getElementById('edit_part_active').checked = getBool(data.active);
            }
        }

        const serviceBtn = e.target.closest('.edit-service-btn');
        if (serviceBtn && serviceBtn.dataset.id && serviceBtn.dataset.id !== 'None') {
            const data = serviceBtn.dataset;
            const form = document.getElementById('editServiceForm');
            if (form) {
                form.action = `/services/edit/${data.id}`;
                if (document.getElementById('edit_service_name')) document.getElementById('edit_service_name').value = getVal(data.name);
                if (document.getElementById('edit_service_description')) document.getElementById('edit_service_description').value = getVal(data.description);
                if (document.getElementById('edit_service_price')) document.getElementById('edit_service_price').value = getVal(data.price);
                if (document.getElementById('edit_service_active')) document.getElementById('edit_service_active').checked = getBool(data.active);
            }
        }
    });
}

/**
 * Initialize generic reload button handler
 */
function initReloadHandler() {
    document.body.addEventListener('click', function(e) {
        if (e.target.closest('#reloadPageBtn')) {
            window.location.reload();
        }
    });
}

/**
 * Initialize generic print button handler
 */
function initPrintHandler() {
    document.body.addEventListener('click', function(e) {
        if (e.target.closest('#printInvoiceBtn')) {
            window.print();
        }
    });
}

/**
 * Initialize form auto-submit for marked elements
 */
function initFormAutoSubmit() {
    document.body.addEventListener('change', function(e) {
        const target = e.target.closest('.auto-submit');
        if (target && e.target.form) {
            // Integrity Fix: Use requestSubmit() to ensure form listeners (like confirmations) are triggered
            if (typeof e.target.form.requestSubmit === 'function') {
                e.target.form.requestSubmit();
            } else {
                e.target.form.submit();
            }
        }
    });
}

/**
 * Initialize global confirmation dialogs for forms and buttons
 */
function initGlobalConfirmations() {
    const getAttr = (el, attr, def) => {
        const val = el.getAttribute(attr);
        return (val && val !== 'None') ? val : def;
    };

    document.body.addEventListener('submit', function(e) {
        const target = e.target.closest('form.confirm-action');
        if (target) {
            // Dependable Localization: Prioritize data-confirm attribute
            const defaultMsg = getAttr(document.body, 'data-default-confirm', 'Are you sure?');
            const confirmAttr = target.getAttribute('data-confirm');
            const msg = (confirmAttr && confirmAttr !== 'None') ? confirmAttr : defaultMsg;
            if (!confirm(msg)) e.preventDefault();
        }
    });

    document.body.addEventListener('click', function(e) {
        const target = e.target.closest('.confirm-action:not(form)');
        if (target) {
            const defaultMsg = getAttr(document.body, 'data-default-confirm', 'Are you sure?');
            const confirmAttr = target.getAttribute('data-confirm');
            const msg = (confirmAttr && confirmAttr !== 'None') ? confirmAttr : defaultMsg;
            if (!confirm(msg)) e.preventDefault();
        }
    });
}

// Integrity: Support live system theme updates when 'System' mode is active
try {
    const systemThemeMedia = window.matchMedia('(prefers-color-scheme: dark)');
    systemThemeMedia.addEventListener('change', () => {
        // Robust check: determine preference from local storage or server-rendered attribute
        const serverPrefAttr = document.body.getAttribute('data-theme-pref');
        const serverPref = (serverPrefAttr && serverPrefAttr !== 'None') ? serverPrefAttr : null;
        const currentPref = serverPref || 
                           (localStorage.getItem('theme') || 'light');
        if (currentPref === 'system') {
            applyTheme('system');
        }
    });
} catch (e) {
    // Storage or matchMedia not supported
}

// ========================================
// CORE ENGINE INITIALIZATION
// ========================================
document.addEventListener('DOMContentLoaded', () => {
    initializeTheme();
    initThemeToggles();
    initDynamicAdminModals();
    initReloadHandler();
    initPrintHandler();
    initFormAutoSubmit();
    initGlobalConfirmations();
});
