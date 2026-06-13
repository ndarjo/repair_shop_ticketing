document.addEventListener('DOMContentLoaded', function() {
    // Note: Global confirmations (.confirm-action) are handled centrally in main.js

    // 2. Payment Modal Logic (Calculator & Balance Filling)
    const payAmtInput = document.getElementById('paymentAmount');
    const fillBtn = document.getElementById('fillBalanceBtn');
    const cashRecInput = document.getElementById('cashReceived');
    const changeDiv = document.getElementById('changeToGive');

    if (fillBtn && payAmtInput) {
        fillBtn.addEventListener('click', function() {
            const bal = parseFloat(payAmtInput.dataset.balance || 0);
            const dec = parseInt(payAmtInput.dataset.decimals || 2);
            payAmtInput.value = bal.toFixed(dec);
            updateChange();
        });
    }

    function updateChange() {
        if (!payAmtInput || !cashRecInput || !changeDiv) return;
        const amt = parseFloat(payAmtInput.value) || 0;
        const rec = parseFloat(cashRecInput.value) || 0;
        const dec = parseInt(payAmtInput.dataset.decimals || 2);
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
            const hasInv = !!partSel.value;
            manName.disabled = hasInv;
            manCost.disabled = hasInv;
            manPrice.disabled = hasInv;
            manName.required = !hasInv;
            manPrice.required = !hasInv;
            if (hasInv) {
                manName.value = '';
                manCost.value = '';
                manPrice.value = '';
            }
        };
        partSel.addEventListener('change', togglePartFields);
        // Initialize state for correct validation on load
        togglePartFields();
    }
});