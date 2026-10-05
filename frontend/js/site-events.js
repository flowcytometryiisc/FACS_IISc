const homeEventTicker = document.querySelector("#home-event-ticker");
const upcomingEventsSection = document.querySelector("#upcoming-events-section");

if (homeEventTicker || upcomingEventsSection) {
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

  void loadFacilityEvents();
}
