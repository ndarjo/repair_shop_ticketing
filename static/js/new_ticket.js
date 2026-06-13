document.addEventListener('DOMContentLoaded', function() {
    const ticketForm = document.getElementById('ticketForm');
    const problemDescription = document.getElementById('problem_description');

    if (!ticketForm || !problemDescription) return;

    ticketForm.addEventListener('submit', function(e) {
        const customerIdInput = document.getElementById('customer_id');
        const deviceIdInput = document.getElementById('device_id');
        
        const customerId = customerIdInput ? customerIdInput.value : null;
        const deviceId = deviceIdInput ? deviceIdInput.value : null;

        if (!customerId || !deviceId) {
            e.preventDefault();
            const msg = ticketForm.getAttribute('data-validation-msg') || 'Please select a customer and a device from the search results before creating the ticket.';
            alert(msg);
        }
    });

    document.querySelectorAll('.problem-quick-select').forEach(button => {
        button.addEventListener('click', function() {
            const problemText = this.getAttribute('data-problem');
            if (!problemText) return;
            const currentVal = problemDescription.value.trim();
            problemDescription.value = currentVal ? `${currentVal}, ${problemText}` : problemText;
            problemDescription.focus();
        });
    });
});