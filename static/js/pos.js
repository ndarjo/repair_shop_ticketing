document.addEventListener('DOMContentLoaded', function() {
    if (!window.POS_CONFIG) return;
    const config = window.POS_CONFIG;
    const itemTypeSelect = document.getElementById('item_type');
    const itemIdSelect = document.getElementById('item_id');
    const includeTaxToggle = document.getElementById('includeTaxToggle');

    function updateItemSelect() {
        if (!itemIdSelect || !itemTypeSelect) return;
        itemIdSelect.innerHTML = '';
        const selectedType = itemTypeSelect.value;
        let items = selectedType === 'service' ? config.services : (selectedType === 'part' ? config.parts : []);

        if (items.length === 0) {
            const option = document.createElement('option');
            option.value = '';
            option.textContent = config.translations.noItems;
            itemIdSelect.appendChild(option);
            itemIdSelect.disabled = true;
        } else {
            itemIdSelect.disabled = false;
            items.forEach(item => {
                const option = document.createElement('option');
                option.value = item.id;
                option.textContent = item.name + (item.sku ? ` (SKU: ${item.sku})` : '');
                itemIdSelect.appendChild(option);
            });
        }
    }

    if (itemTypeSelect) {
        itemTypeSelect.addEventListener('change', updateItemSelect);
        updateItemSelect();
    }

    function renderSummary(data) {
        const fields = {
            'subtotal_amount': data.subtotal_amount,
            'tax_amount': data.tax_amount,
            'discount_amount_display': data.discount_amount,
            'loyalty_discount_display': data.loyalty_discount,
            'total_amount': data.total_amount,
            'balance_due': data.balance_due,
            'modal_balance_due': data.balance_due
        };
        Object.entries(fields).forEach(([id, val]) => {
            const el = document.getElementById(id);
            if (el) el.textContent = val;
        });
        const taxRateEl = document.getElementById('tax_rate_display');
        if(taxRateEl) taxRateEl.textContent = parseFloat(data.tax_rate).toFixed(2);
        const estPointsEl = document.getElementById('est_points_display');
        if(estPointsEl) estPointsEl.textContent = `+${data.est_points} ${config.translations.pts}`;
        const payAmtEl = document.getElementById('payment_amount');
        if (payAmtEl) {
            // Dependable Localization: Handle both dot and comma decimal separators for robust numeric parsing
            const normalizedValue = data.balance_due.replace(/[^\d.,-]/g, '').replace(',', '.');
            payAmtEl.value = parseFloat(normalizedValue).toFixed(config.currencyDecimals);
        }
        const taxRow = document.querySelector('#tax_amount')?.closest('tr');
        if (taxRow) data.include_tax ? taxRow.classList.remove('text-muted') : taxRow.classList.add('text-muted');
    }

    async function updateSummary(url, body) {
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': config.csrfToken },
                body: JSON.stringify(body)
            });
            const data = await response.json();
            if (data.success) {
                renderSummary(data);
            } else { 
                alert(data.message || config.translations.updateError); 
            }
        } catch (e) { 
            console.error(e);
            alert(config.translations.updateError);
        }
    }

    document.querySelectorAll('.update-item-form').forEach(form => {
        form.addEventListener('submit', async function(e) {
            e.preventDefault();
            const url = config.urls.updateItemDetails.replace('/0', `/${this.dataset.itemId}`);
            try {
                const res = await fetch(url, { method: 'POST', body: new FormData(this), headers: { 'X-CSRFToken': config.csrfToken } });
                const data = await res.json();
                if (data.success) renderSummary(data);
                else alert(data.message);
            } catch (err) { alert(config.translations.updateError); }
        });
    });

    if (includeTaxToggle) {
        includeTaxToggle.addEventListener('change', () => {
            updateSummary(config.urls.toggleTax, { include_tax: includeTaxToggle.checked });
        });
    }

    const discBtn = document.getElementById('applyDiscountBtn');
    if (discBtn) {
        discBtn.addEventListener('click', () => {
            updateSummary(config.urls.updateDiscount, {
                discount_amount: document.getElementById('discount_amount_input').value,
                discount_type: document.getElementById('discount_type_input').value
            });
        });
    }

    const loyaltyBtn = document.getElementById('redeemLoyaltyBtn');
    if (loyaltyBtn) {
        loyaltyBtn.addEventListener('click', () => {
            updateSummary(config.urls.redeemLoyalty, { points: document.getElementById('loyalty_points_input').value });
        });
    }
});