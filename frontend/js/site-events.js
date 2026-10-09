const homeEventTicker = document.querySelector("#home-event-ticker");
const upcomingEventsSection = document.querySelector("#upcoming-events-section");
const eventGallery = document.querySelector("#event-gallery-grid");

if (homeEventTicker || upcomingEventsSection || eventGallery) {
  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }

  function formatEventDate(value) {
    return new Intl.DateTimeFormat("en-IN", {
      day: "numeric", month: "short", year: "numeric",
    }).format(new Date(`${value}T12:00:00`));
  }

  function eventDates(item) {
    return item.startDate === item.endDate
      ? formatEventDate(item.startDate)
      : `${formatEventDate(item.startDate)} – ${formatEventDate(item.endDate)}`;
  }

  function eventLabel(item) {
    return item.category === "workshop" ? "Workshop" : "Facility event";
  }

  function renderTickerItem(item, decorative = false) {
    return `<article class="home-event-ticker-item">
      <span class="home-event-ticker-type">${escapeHTML(eventLabel(item))} · ${escapeHTML(eventDates(item))}</span>
      <strong>${escapeHTML(item.title)}</strong>
      <span class="home-event-ticker-summary">${escapeHTML(item.summary)}</span>
      <a href="${escapeHTML(item.linkUrl)}"${decorative ? ' tabindex="-1"' : ""}>${escapeHTML(item.linkLabel)} <span aria-hidden="true">↗</span></a>
    </article>`;
  }

  function renderWorkshopItem(item) {
    return `<article class="upcoming-event-card ${escapeHTML(item.category)}">
      <div class="upcoming-event-date"><span>${escapeHTML(eventLabel(item))}</span><strong>${escapeHTML(eventDates(item))}</strong></div>
      <div class="upcoming-event-copy">
        ${item.imageUrl ? `<img class="upcoming-event-photo" src="${escapeHTML(item.imageUrl)}" alt="${escapeHTML(item.title)}" loading="lazy" decoding="async">` : ""}
        <h3>${escapeHTML(item.title)}</h3>
        <p class="upcoming-event-summary">${escapeHTML(item.summary)}</p>
        <p>${escapeHTML(item.description)}</p>
        <a class="btn primary" href="${escapeHTML(item.linkUrl)}" target="_blank" rel="noopener noreferrer">${escapeHTML(item.linkLabel)} <b>↗</b></a>
      </div>
    </article>`;
  }

  async function loadFacilityEvents() {
    try {
      const response = await fetch("/api/events", { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Upcoming facility events could not be loaded.");
      if (!Array.isArray(payload.events)) throw new Error("The facility events response was invalid.");
      const events = payload.events;

      if (homeEventTicker && events.length) {
        const items = events.map(item => renderTickerItem(item)).join("");
        const decorativeItems = events.map(item => renderTickerItem(item, true)).join("");
        homeEventTicker.querySelector("#home-event-ticker-track").innerHTML = `
          <div class="home-event-ticker-group">${items}</div>
          <div class="home-event-ticker-group" aria-hidden="true">${decorativeItems}</div>`;
        homeEventTicker.hidden = false;
      }

      if (upcomingEventsSection && events.length) {
        upcomingEventsSection.querySelector("#upcoming-events-list").innerHTML =
          events.map(renderWorkshopItem).join("");
        upcomingEventsSection.hidden = false;
        document.querySelector(".upcoming-workshop-note")?.setAttribute("hidden", "");
      }
    } catch (error) {
      console.error("Unable to load upcoming facility events.", error);
    }
  }

  async function loadWorkshopArchive() {
    const summary = document.querySelector("#workshop-archive-summary");
    if (!summary) return;
    try {
      const response = await fetch("/api/workshops/archive", { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Archived workshop content could not be loaded.");
      if (typeof payload.summary !== "string") throw new Error("The archived workshop response was invalid.");
      summary.textContent = payload.summary;
    } catch (error) {
      console.error("Unable to load archived workshop content.", error);
    }
  }

  async function loadEventGallery() {
    if (!eventGallery) return;
    try {
      const response = await fetch("/api/gallery", { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Event photos could not be loaded.");
      if (!Array.isArray(payload.items)) throw new Error("The event gallery response was invalid.");
      eventGallery.innerHTML = payload.items.length
        ? payload.items.map(item => `<article class="event-gallery-card">
            <img src="${escapeHTML(item.imageUrl)}" alt="${escapeHTML(item.description)}" loading="lazy" decoding="async">
            <div class="event-gallery-card-details"><h3>${escapeHTML(item.eventName)}</h3>${item.eventDate ? `<time datetime="${escapeHTML(item.eventDate)}">${escapeHTML(formatEventDate(item.eventDate))}</time>` : ""}
            <p>${escapeHTML(item.description)}</p>
            </div>
          </article>`).join("")
        : '<p class="gallery-empty">No event photos have been added yet.</p>';
    } catch (error) {
      console.error("Unable to load the event gallery.", error);
      eventGallery.innerHTML = '<p class="gallery-empty">Event photos could not be loaded right now. Please try again later.</p>';
    }
  }

  const workshopsTab = document.querySelector("#workshops-tab");
  const galleryTab = document.querySelector("#gallery-tab");
  if (workshopsTab && galleryTab) {
    function selectWorkshopTab(gallerySelected) {
      workshopsTab.setAttribute("aria-selected", String(!gallerySelected));
      galleryTab.setAttribute("aria-selected", String(gallerySelected));
      workshopsTab.classList.toggle("active", !gallerySelected);
      galleryTab.classList.toggle("active", gallerySelected);
      document.querySelector("#workshops-tab-panel").hidden = gallerySelected;
      document.querySelector("#gallery-tab-panel").hidden = !gallerySelected;
    }

    document.querySelectorAll(".workshop-page-tab").forEach(tab => {
      tab.addEventListener("click", () => {
        const gallerySelected = tab.id === "gallery-tab";
        if (galleryTab.getAttribute("aria-selected") === String(gallerySelected)) return;
        selectWorkshopTab(gallerySelected);
        const tabHash = gallerySelected ? "#gallery" : "";
        window.history.pushState(null, "", `${window.location.pathname}${window.location.search}${tabHash}`);
      });
    });
    window.addEventListener("popstate", () => {
      selectWorkshopTab(window.location.hash === "#gallery");
    });
    selectWorkshopTab(window.location.hash === "#gallery");
  }

  void loadFacilityEvents();
  void loadWorkshopArchive();
  void loadEventGallery();
}
