// ========================================
// REPAIR SHOP TICKETING SYSTEM
// Ticket Detail & Financial Updates
// ========================================

document.addEventListener('DOMContentLoaded', function() {
    const container = document.getElementById('financialSummaryContainer');
    if (!container) return;

    const ticketId = container.dataset.ticketId;
    const currencySymbol = container.dataset.currencySymbol;
    const currencyDecimals = parseInt(container.dataset.currencyDecimals) || 2;

    const quickTaxToggle = document.getElementById('quickTaxToggle');

    async function updateTicketSummary() {
        try {
            const response = await fetch(`/ticket/summary/${ticketId}`, {
                method: 'GET',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            const data = await response.json().catch(() => ({}));
            if (response.ok && data.success) {
                const subtotalEl = document.getElementById('subtotal_display');
                const taxAmountEl = document.getElementById('tax_amount_display');
                
                if (subtotalEl) subtotalEl.textContent = data.subtotal_amount;
                if (taxAmountEl) taxAmountEl.textContent = data.tax_amount;
                
                const discountDisplay = document.getElementById('discount_amount_display'); // Conditionally rendered
                if (discountDisplay && data.discount_amount) discountDisplay.textContent = data.discount_amount;
                
                const loyaltyDiscountDisplay = document.getElementById('loyalty_discount_display'); // Conditionally rendered
                if (loyaltyDiscountDisplay && data.loyalty_discount) loyaltyDiscountDisplay.textContent = data.loyalty_discount;
                
                const grandTotalEl = document.getElementById('grand_total_display');
                const totalPaidEl = document.getElementById('total_paid_display');
                
                if (grandTotalEl) grandTotalEl.textContent = data.grand_total;
                if (totalPaidEl) totalPaidEl.textContent = data.total_paid;
                
                const balanceDueEl = document.getElementById('balance_due_display');
                const balanceDueLbl = document.getElementById('balance_due_label');
                const balanceDueRowEl = document.getElementById('balanceDueRow');
                
                if (balanceDueEl && balanceDueRowEl) {
                    balanceDueEl.textContent = data.balance_due;
                    
                    // Dependable Localization: Handle both dot and comma decimal separators for robust sign detection
                    const normalizedValue = data.balance_due.replace(/[^\d.,-]/g, '').replace(',', '.');
                    const rawValue = parseFloat(normalizedValue);
                    
                    if (!isNaN(rawValue) && rawValue > 0) {
                        balanceDueRowEl.classList.remove('text-success');
                        balanceDueRowEl.classList.add('text-danger');
                        if (balanceDueLbl) balanceDueLbl.textContent = balanceDueEl.dataset.balanceDueText;
                    } else if (!isNaN(rawValue)) {
                        balanceDueRowEl.classList.remove('text-danger');
                        balanceDueRowEl.classList.add('text-success');
                        if (balanceDueLbl) balanceDueLbl.textContent = balanceDueEl.dataset.changeDueText;
                    } else {
                        balanceDueRowEl.classList.remove('text-danger');
                        balanceDueRowEl.classList.add('text-success');
                        if (balanceDueLbl) balanceDueLbl.textContent = balanceDueEl.dataset.changeDueText;
                    }
                }

                const pointsPreviewEl = document.getElementById('points_preview');
                if (pointsPreviewEl) pointsPreviewEl.textContent = `+${data.est_points} ${container.dataset.pointsLabel || 'pts'}`;

                if (taxAmountEl) {
                    const taxRow = taxAmountEl.closest('div');
                    if (taxRow) data.include_tax ? taxRow.classList.remove('text-muted') : taxRow.classList.add('text-muted');
                }
                if (subtotalEl) {
                    const subtotalRow = subtotalEl.closest('div');
                    if (subtotalRow) data.include_tax ? subtotalRow.classList.remove('text-muted') : subtotalRow.classList.add('text-muted');
                }
            } else {
                const fallbackMsg = container.dataset.errorUpdate || 'Failed to update summary.';
                alert(data.error || data.message || fallbackMsg);
            }
        } catch (e) { 
            console.error(e); 
            const errorMsg = container.dataset.errorUpdate || 'An error occurred while updating the summary.';
            alert(errorMsg); 
        }
    }

    if (quickTaxToggle) {
        quickTaxToggle.addEventListener('change', async function() {
            try {
                const response = await fetch(`/ticket/toggle_tax/${ticketId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                    body: JSON.stringify({ include_tax: this.checked })
                });
                if (response.ok) {
                    updateTicketSummary();
                } else {
                    const data = await response.json().catch(() => ({}));
                    const fallbackMsg = container.dataset.errorTax || 'Failed to toggle tax.';
                    alert(data.message || fallbackMsg);
                    this.checked = !this.checked; // Revert toggle state on error
                }
            } catch (e) { 
                console.error('Tax toggle failed', e); 
                const errorMsg = container.dataset.errorTax || 'An error occurred while toggling tax.';
                alert(errorMsg); 
            }
        });
    }
});