document.addEventListener('DOMContentLoaded', function() {
    const editModal = document.getElementById('editLocationModal');
    const editForm = document.getElementById('editLocationForm');
    
    // 1. Populate Edit Modal using the show.bs.modal event
    if (editModal && editForm) {
        editModal.addEventListener('show.bs.modal', function(event) {
            const button = event.relatedTarget; // Button that triggered the modal
            
            // INTEGRITY: Only populate if triggered by a button.
            // If opened via JS (relatedTarget is null), it's likely a validation error return.
            if (!button) return;

            /**
             * Helper to extract attributes and handle Python's "None" string representation
             * to ensure a clean UI and data integrity.
             */
            const getVal = (attr) => {
                const val = button.getAttribute(attr);
                return (val && val !== 'None') ? val : '';
            };

            const id = getVal('data-id');
            if (id) {
                editForm.action = `/admin/locations/edit/${id}`;
                
                const name = document.getElementById('editLocationName');
                const addr = document.getElementById('editLocationAddress');
                const phon = document.getElementById('editLocationPhone');
                const email = document.getElementById('editLocationEmail');
                
                if (name) name.value = getVal('data-name');
                if (addr) addr.value = getVal('data-address');
                if (phon) phon.value = getVal('data-phone');
                if (email) email.value = getVal('data-email');
            }
        });
    }

    // 2. UX Fix: Auto-open modals if returning with validation errors
    // Ensures a consistent experience when form validation fails.
    if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
        // Handle Add Modal
        const addModalEl = document.getElementById('addLocationModal');
        if (addModalEl && addModalEl.querySelector('.is-invalid')) {
            bootstrap.Modal.getOrCreateInstance(addModalEl).show();
        }

        // Handle Edit Modal
        if (editModal && editModal.querySelector('.is-invalid')) {
            bootstrap.Modal.getOrCreateInstance(editModal).show();
        }
    }
});