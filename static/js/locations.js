document.addEventListener('DOMContentLoaded', function() {
    const editModal = document.getElementById('editLocationModal');
    const editForm = document.getElementById('editLocationForm');
    
    // 1. Populate Edit Modal using the show.bs.modal event
    if (editModal && editForm) {
        editModal.addEventListener('show.bs.modal', function(event) {
            const button = event.relatedTarget; // Button that triggered the modal
            const id = button.getAttribute('data-id');
            
            editForm.action = `/admin/locations/edit/${id}`;
            document.getElementById('editLocationName').value = button.getAttribute('data-name') || '';
            document.getElementById('editLocationAddress').value = button.getAttribute('data-address') || '';
            document.getElementById('editLocationPhone').value = button.getAttribute('data-phone') || '';
            document.getElementById('editLocationEmail').value = button.getAttribute('data-email') || '';
        });
    }

    // 2. UX Fix: Auto-open the Add modal if returning with form data (validation error)
    const addModalEl = document.getElementById('addLocationModal');
    
    const hasFormData = addModalEl && Array.from(addModalEl.querySelectorAll('input:not([type="hidden"]), textarea')).some(i => i.value.trim() !== "");

    if (addModalEl && hasFormData) {
        bootstrap.Modal.getOrCreateInstance(addModalEl).show();
    }
});