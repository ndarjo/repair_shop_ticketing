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
    
    let displayTheme = theme;
    if (theme === 'system') {
        displayTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    // Update data attribute
    html.dataset.theme = displayTheme;
    
    // Update body class
    body.classList.remove('theme-light', 'theme-dark');
    if (displayTheme) body.classList.add(`theme-${displayTheme}`);
    
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
    
    // Remove all color classes
    body.classList.remove('color-blue', 'color-green', 'color-purple', 'color-red', 'color-orange');
    
    // Add new color class
    if (color) body.classList.add(`color-${color}`);
    
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
    const serverTheme = body.getAttribute('data-theme-pref');
    const serverColor = body.getAttribute('data-color-pref');

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
    
    try {
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';

        const response = await fetch(url, {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': getCsrfToken()
            }
        });
        
        if (response.ok) {
            const data = await response.json();
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
                successCallback(data.id, displayName);
            }
            form.reset();
        } else {
            const errorData = await response.json().catch(() => ({}));
            alert(`Error: ${errorData.error || response.statusText || 'Operation failed'}`);
        }
    } catch (error) {
        console.error('Error:', error);
        alert('A network or server error occurred. Please try again.');
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
    document.body.addEventListener('click', function(e) {
        const partBtn = e.target.closest('.edit-part-btn');
        if (partBtn && partBtn.dataset.id) {
            const data = partBtn.dataset;
            const form = document.getElementById('editPartForm');
            if (form) {
                form.action = `/inventory/edit/${data.id}`;
                if (document.getElementById('edit_part_name')) document.getElementById('edit_part_name').value = data.name || '';
                if (document.getElementById('edit_part_cost')) document.getElementById('edit_part_cost').value = data.cost || '';
                if (document.getElementById('edit_part_price')) document.getElementById('edit_part_price').value = data.price || '';
                if (document.getElementById('edit_part_stock')) document.getElementById('edit_part_stock').value = data.stock || '0';
                if (document.getElementById('edit_part_active')) document.getElementById('edit_part_active').checked = data.active === 'true';
            }
        }

        const serviceBtn = e.target.closest('.edit-service-btn');
        if (serviceBtn && serviceBtn.dataset.id) {
            const data = serviceBtn.dataset;
            const form = document.getElementById('editServiceForm');
            if (form) {
                form.action = `/services/edit/${data.id}`;
                if (document.getElementById('edit_service_name')) document.getElementById('edit_service_name').value = data.name || '';
                if (document.getElementById('edit_service_description')) document.getElementById('edit_service_description').value = data.description || '';
                if (document.getElementById('edit_service_price')) document.getElementById('edit_service_price').value = data.price || '';
                if (document.getElementById('edit_service_active')) document.getElementById('edit_service_active').checked = data.active === 'true';
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
            e.target.form.submit();
        }
    });
}

/**
 * Initialize global confirmation dialogs for forms and buttons
 */
function initGlobalConfirmations() {
    document.body.addEventListener('submit', function(e) {
        const target = e.target.closest('form.confirm-action');
        if (target) {
            const msg = target.dataset.confirm || 'Are you sure?';
            if (!confirm(msg)) e.preventDefault();
        }
    });

    document.body.addEventListener('click', function(e) {
        const target = e.target.closest('.confirm-action:not(form)');
        if (target) {
            const msg = target.dataset.confirm || 'Are you sure?';
            if (!confirm(msg)) e.preventDefault();
        }
    });
}

// Integrity: Support live system theme updates when 'System' mode is active
try {
    const systemThemeMedia = window.matchMedia('(prefers-color-scheme: dark)');
    systemThemeMedia.addEventListener('change', () => {
        // Robust check: determine preference from local storage or server-rendered attribute
        const currentPref = localStorage.getItem('theme') || 
                           document.body.getAttribute('data-theme-pref');
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
