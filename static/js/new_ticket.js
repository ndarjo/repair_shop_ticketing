document.addEventListener('DOMContentLoaded', function() {
    const ticketForm = document.getElementById('ticketForm');
    const problemDescription = document.getElementById('problem_description');
    const customerIdInput = document.getElementById('customer_id');
    const deviceIdInput = document.getElementById('device_id');

    if (!ticketForm || !problemDescription || !customerIdInput || !deviceIdInput) return;

    // Integrity: Filter out technical null artifacts and trim whitespace
    const getVal = (v) => (v && v !== 'None') ? v.trim() : '';

    ticketForm.addEventListener('submit', function(e) {
        const customerId = getVal(customerIdInput.value);
        const deviceId = getVal(deviceIdInput.value);

        if (!customerId || !deviceId) {
            e.preventDefault();
            // Localization: Prioritize server-rendered message
            const msg = getVal(ticketForm.getAttribute('data-validation-msg')) || 'Please select a customer and a device from the search results before creating the ticket.';
            alert(msg);
        }
    });

    document.querySelectorAll('.problem-quick-select').forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault(); // Integrity: Prevent accidental form submission
            const problemText = getVal(this.getAttribute('data-problem'));
            if (!problemText) return;
            
            const currentVal = problemDescription.value.trim();
            // Integrity: Strip trailing commas and redundant whitespace for clean duplicate detection and formatting
            const cleanVal = currentVal.replace(/[\s,]+$/, "");
            const existing = cleanVal ? cleanVal.split(',').map(p => p.trim().toLowerCase()).filter(p => p !== "") : [];
            
            // UX Integrity: Prevent duplicate entries (case-insensitive) and maintain clean formatting
            if (!existing.includes(problemText.toLowerCase())) {
                problemDescription.value = cleanVal ? `${cleanVal}, ${problemText}` : problemText;
            }
            
            problemDescription.focus();
        });
    });
});