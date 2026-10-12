const facilityDocumentList = document.querySelector("#facility-document-list");

if (facilityDocumentList) {
  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[character]);
  }

  async function loadFacilityDocuments() {
    try {
      const response = await fetch("/api/documents", { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Facility documents could not be loaded.");
      }
      facilityDocumentList.innerHTML = payload.items.length
        ? payload.items.map(item => `<a class="document-row" href="${escapeHTML(item.url)}" target="_blank" rel="noopener noreferrer">
            <span class="document-icon">PDF</span>
            <span><strong>${escapeHTML(item.title)}</strong><small>${escapeHTML(item.description || item.filename || "Facility document · PDF")}</small></span>
            <b>View PDF ↗</b>
          </a>`).join("")
        : '<p class="document-status">No facility documents are available at this time.</p>';
    } catch (error) {
      facilityDocumentList.innerHTML = `<p class="document-status" role="status">${escapeHTML(error.message)}</p>`;
    }
  }

  void loadFacilityDocuments();
}
