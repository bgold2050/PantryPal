document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("manual-entry-form");

    form.addEventListener("submit", function (event) {
        let valid = true;

        // Clear previous error messages
        document.querySelectorAll('.invalid-feedback').forEach(function (el) {
            el.textContent = '';
        });

        // Validate Barcode or PLU
        const barcodeOrPlu = document.getElementById("barcode_or_plu").value;
        if (barcodeOrPlu.trim() === "") {
            document.getElementById("barcodeError").textContent = "Barcode or PLU is required.";
            valid = false;
        }

        // Validate Item Name
        const name = document.getElementById("name").value;
        if (name.trim() === "") {
            document.getElementById("nameError").textContent = "Item name is required.";
            valid = false;
        }

        // Validate Quantity
        const quantity = document.getElementById("quantity").value;
        if (quantity <= 0) {
            document.getElementById("quantityError").textContent = "Quantity must be greater than zero.";
            valid = false;
        }

        // Validate Location
        const locationSelect = document.getElementById("locationSelect");
        if (locationSelect.value === "") {
            document.getElementById("locationError").textContent = "Please select a location.";
            valid = false;
        }

        if (!valid) {
            event.preventDefault(); // Prevent form submission if validation fails
        }
    });
});
