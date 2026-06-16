document.addEventListener('DOMContentLoaded', function() {
    // Note: Global confirmations (.confirm-action) are handled centrally in main.js

    // Integrity: Filter out technical null artifacts common in server-rendered templates
    const getVal = (v) => (v && v !== 'None') ? v.trim() : '';

    // 1. UX Fix: Auto-open modals if returning with validation errors
    // Ensures a consistent experience when form validation fails.
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
        document.querySelectorAll('.modal').forEach(modalEl => {
            if (modalEl.querySelector('.is-invalid')) {
                bootstrap.Modal.getOrCreateInstance(modalEl).show();
            }
        });
    }

    // 2. Payment Modal Logic (Calculator & Balance Filling)
    const payAmtInput = document.getElementById('paymentAmount');
    const fillBtn = document.getElementById('fillBalanceBtn');
    const cashRecInput = document.getElementById('cashReceived');
    const changeDiv = document.getElementById('changeToGive');

    if (fillBtn && payAmtInput) {
        fillBtn.addEventListener('click', function() {
            // Integrity: Robust parsing for currency values and decimals
            const balAttr = getVal(payAmtInput.dataset.balance);
            const decAttr = getVal(payAmtInput.dataset.decimals);
            const bal = parseFloat(balAttr) || 0;
            const parsedDec = parseInt(decAttr, 10);
            const dec = isNaN(parsedDec) ? 2 : parsedDec;
            payAmtInput.value = isNaN(bal) ? (0).toFixed(dec) : bal.toFixed(dec);
            updateChange();
        });
    }

    function updateChange() {
        if (!payAmtInput || !cashRecInput || !changeDiv) return;
        const amt = parseFloat(payAmtInput.value) || 0;
        const rec = parseFloat(cashRecInput.value) || 0;
        const decAttr = getVal(payAmtInput.dataset.decimals);
        const parsedDec = parseInt(decAttr, 10);
        const dec = isNaN(parsedDec) ? 2 : parsedDec;
        const diff = rec - amt;
        changeDiv.textContent = (diff > 0 ? diff : 0).toFixed(dec);
    }

    if (payAmtInput) payAmtInput.addEventListener('input', updateChange);
    if (cashRecInput) cashRecInput.addEventListener('input', updateChange);

    // 3. Add Part Modal Logic (Toggle Manual vs Inventory)
    const partSel = document.getElementById('partSelect');
    const manName = document.getElementById('manualPartName');
    const manCost = document.getElementById('partCost');
    const manPrice = document.getElementById('partPrice');

    if (partSel) {
        const togglePartFields = function() {
            const hasInv = !!getVal(partSel.value);
            
            if (manName) {
                manName.disabled = hasInv;
                manName.required = !hasInv;
                if (hasInv) manName.value = '';
            }
            
            if (manCost) {
                manCost.disabled = hasInv;
                if (hasInv) manCost.value = '';
            }
            
            if (manPrice) {
                manPrice.disabled = hasInv;
                manPrice.required = !hasInv;
                if (hasInv) manPrice.value = '';
            }
        };
        
        partSel.addEventListener('change', togglePartFields);
        // Initialize state for correct validation on load
        togglePartFields();
    }

    // 4. SKU Quick Search Logic
    const skuSearch = document.getElementById('partSkuSearch');
    if (skuSearch && partSel) {
        skuSearch.addEventListener('input', function() {
            const val = this.value.trim().toLowerCase();
            if (!val) return;

            for (let i = 0; i < partSel.options.length; i++) {
                const opt = partSel.options[i];
                const skuVal = getVal(opt.dataset.sku).toLowerCase();
                if (skuVal && (skuVal === val || skuVal.startsWith(val))) {
                    partSel.selectedIndex = i;
                    partSel.dispatchEvent(new Event('change'));
                    break;
                }
            }
        });
    }
});