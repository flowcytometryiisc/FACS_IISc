const bookingDocumentLinks = document.querySelector("#booking-document-links");

if (bookingDocumentLinks) {
  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[character]);
  }

  async function loadBookingDocuments() {
    try {
      const response = await fetch("/api/documents", { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Booking forms could not be loaded.");
      }
      const inhouseForm = payload.items.find(item => {
        const documentDetails = `${item.title} ${item.description} ${item.filename}`;
        return /in[\s-]?house|internal/i.test(documentDetails)
          || (/iisc/i.test(documentDetails) && /booking|form|user/i.test(documentDetails));
      });
      const externalForm = payload.items.find(item =>
        /external/i.test(`${item.title} ${item.description} ${item.filename}`)
      );
      const forms = [
        inhouseForm && { label: "Booking form for IISc users", item: inhouseForm },
        externalForm && { label: "External booking form", item: externalForm },
      ].filter(Boolean);
      bookingDocumentLinks.innerHTML = forms.length
        ? forms.map(({ label, item }) => `<a class="booking-document-link" href="${escapeHTML(item.url)}" target="_blank" rel="noopener noreferrer">
            <span><strong>${escapeHTML(label)}</strong><small>${escapeHTML(item.title)}</small></span><b aria-hidden="true">↗</b>
          </a>`).join("")
        : '<a class="booking-document-fallback" href="forms-resources.html">View available forms &amp; documents →</a>';
    } catch (error) {
      bookingDocumentLinks.innerHTML = `<a class="booking-document-fallback" href="forms-resources.html">${escapeHTML(error.message)} · View forms &amp; documents →</a>`;
    }
  }

  void loadBookingDocuments();
}
