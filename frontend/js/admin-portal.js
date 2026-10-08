const adminPortal = document.querySelector("[data-admin-portal]");

if (adminPortal) {
  const apiBase = "/api";
  const loginPanel = adminPortal.querySelector("#admin-login-panel");
  const dashboard = adminPortal.querySelector("#admin-dashboard");
  const loginForm = adminPortal.querySelector("#admin-login-form");
  const loginStatus = adminPortal.querySelector("#admin-login-status");
  const dashboardStatus = adminPortal.querySelector("#admin-dashboard-status");
  const dashboardTitle = adminPortal.querySelector("#admin-dashboard-title");
  const dashboardDescription = adminPortal.querySelector("#admin-dashboard-description");
  const dashboardHomeButton = adminPortal.querySelector("#admin-dashboard-home");
  const dashboardCards = adminPortal.querySelector(".admin-dashboard-cards");
  const dashboardViewButtons = [...adminPortal.querySelectorAll("[data-admin-view-button]")];
  const dashboardViewPanels = [...adminPortal.querySelectorAll("[data-admin-view-panel]")];
  const bookingList = adminPortal.querySelector("#admin-booking-list");
  const searchInput = adminPortal.querySelector("#admin-search");
  const statusFilter = adminPortal.querySelector("#admin-status-filter");
  const detailDialog = document.querySelector("#admin-booking-detail");
  const detailContent = document.querySelector("#admin-detail-content");
  const itemConfirmDialog = document.querySelector("#admin-item-confirm");
  const itemConfirmEyebrow = document.querySelector("#admin-item-confirm-eyebrow");
  const itemConfirmTitle = document.querySelector("#admin-item-confirm-title");
  const itemConfirmName = document.querySelector("#admin-item-confirm-name");
  const itemConfirmDescription = document.querySelector("#admin-item-confirm-description");
  const itemConfirmStatus = document.querySelector("#admin-item-confirm-status");
  const itemConfirmButton = document.querySelector("#admin-confirm-remove-item");
  const itemConfirmCancelButton = itemConfirmDialog.querySelector("[data-cancel-item-removal]");
  const calendarMonthInput = adminPortal.querySelector("#admin-calendar-month");
  const calendarStatus = adminPortal.querySelector("#admin-calendar-status");
  const calendarEvents = adminPortal.querySelector("#admin-calendar-events");
  const calendarInstrumentFilter = adminPortal.querySelector("#admin-calendar-instrument");
  const closureList = adminPortal.querySelector("#admin-closure-list");
  const eventForm = adminPortal.querySelector("#admin-event-form");
  const eventList = adminPortal.querySelector("#admin-event-list");
  const eventFormStatus = adminPortal.querySelector("#admin-event-form-status");
  const eventFormTitle = adminPortal.querySelector("#admin-event-form-title");
  const eventCancelEditButton = adminPortal.querySelector("#admin-event-cancel-edit");
  const workshopContentList = adminPortal.querySelector("#admin-workshop-content-list");
  const workshopContentStatus = adminPortal.querySelector("#admin-workshop-content-status");
  const brownBearAdminLink = adminPortal.querySelector("#admin-brownbear-admin");
  const editDialog = document.querySelector("#admin-edit-booking");
  const editForm = document.querySelector("#admin-edit-form");
  const editSlots = document.querySelector("#admin-edit-slots-list");
  const editStatus = document.querySelector("#admin-edit-status");
  const bookingTimes = ["10:00-11:00", "11:00-12:00", "12:00-13:00", "14:00-15:00", "15:00-16:00", "16:00-17:00"];
  let bookings = [];
  let instruments = [];
  let editingBookingId = "";
  let creatingBooking = false;
  let currentCalendarEvents = [];
  let calendarClosures = [];
  let facilityEvents = [];
  let workshopArchive = null;
  let eventContentItems = [];
  let pendingRemoval = null;
  let calendarFetchedAt = "";
  let selectedCalendarDate = "";
  let calendarRequestId = 0;
  let csrfToken = "";
  let inactivityTimer = 0;
  const inactivityTimeoutMs = 15 * 60 * 1000;

  function showDashboardHome() {
    dashboardTitle.textContent = "Admin dashboard";
    dashboardDescription.textContent = "Choose a workspace to manage the facility.";
    dashboardHomeButton.hidden = true;
    dashboardCards.hidden = false;
    dashboardViewPanels.forEach(panel => {
      panel.hidden = true;
    });
    dashboardViewButtons.forEach(button => {
      button.classList.remove("active");
      button.setAttribute("aria-pressed", "false");
    });
  }

  function selectDashboardView(viewName) {
    const workspaces = {
      bookings: ["Bookings", "Review requests, manage bookings, and sync the facility calendar."],
      events: ["Events & workshops", "Publish facility announcements and manage calendar closures."],
      "workshop-content": ["Event & workshop content", "Update event and workshop summaries and photos shown on the public website."],
      statistics: ["Usage statistics", "Explore monthly facility activity and demand."],
    };
    const workspace = workspaces[viewName];
    if (!workspace) return;
    dashboardTitle.textContent = workspace[0];
    dashboardDescription.textContent = workspace[1];
    dashboardHomeButton.hidden = false;
    dashboardCards.hidden = true;
    dashboardViewButtons.forEach(button => {
      const selected = button.dataset.adminViewButton === viewName;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    dashboardViewPanels.forEach(panel => {
      panel.hidden = panel.dataset.adminViewPanel !== viewName;
    });
    if (viewName === "statistics") {
      document.dispatchEvent(new Event("admin:statistics-opened"));
    }
    if (viewName === "workshop-content") void loadWorkshopContent();
  }

  dashboardViewButtons.forEach(button => {
    button.addEventListener("click", () => selectDashboardView(button.dataset.adminViewButton));
  });
  dashboardHomeButton.addEventListener("click", showDashboardHome);
  adminPortal.querySelector("#admin-create-event").addEventListener("click", () => {
    selectDashboardView("events");
    eventForm.elements.namedItem("title").focus();
  });

  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[character]);
  }

  function formatDate(value) {
    return new Intl.DateTimeFormat("en-IN", {
      weekday: "short", day: "numeric", month: "short", year: "numeric"
    }).format(new Date(`${value}T12:00:00`));
  }

  function formatTimeSlot(value) {
    return value.split("-").map(part => {
      const [hourText, minute] = part.split(":");
      const hour = Number(hourText);
      return `${hour % 12 || 12}:${minute} ${hour < 12 ? "AM" : "PM"}`;
    }).join(" – ");
  }

  function requestManagedItemRemoval(kind, id) {
    const item = kind === "closure"
      ? calendarClosures.find(closure => closure.id === id)
      : facilityEvents.find(facilityEvent => facilityEvent.id === id);
    if (!item) {
      dashboardStatus.textContent = `This ${kind} is no longer in the list. Refresh and try again.`;
      return;
    }
    const isClosure = kind === "closure";
    const label = isClosure
      ? item.type === "exception" ? "Exception holiday" : "Workshop holiday"
      : item.category === "workshop" ? "Workshop" : "Facility event";
    const dates = item.startDate === item.endDate
      ? formatDate(item.startDate)
      : `${formatDate(item.startDate)} – ${formatDate(item.endDate)}`;
    itemConfirmEyebrow.textContent = isClosure ? "CALENDAR CLOSURE" : "EVENT CONTENT";
    itemConfirmTitle.textContent = isClosure ? "Remove this closure?" : "Delete this event?";
    itemConfirmName.textContent = `${label} · ${dates} · ${isClosure ? item.remark : item.title}`;
    itemConfirmDescription.textContent = isClosure
      ? "Removing it may make the affected booking sessions available again."
      : "This event will be removed from the homepage ticker and the Events & Workshop page.";
    itemConfirmCancelButton.textContent = isClosure ? "Keep closure" : "Keep event";
    itemConfirmButton.textContent = isClosure ? "Remove closure" : "Delete event";
    itemConfirmStatus.textContent = "";
    pendingRemoval = { kind, id };
    itemConfirmDialog.showModal();
  }

  async function removeManagedItem() {
    if (!pendingRemoval) return;
    const removal = pendingRemoval;
    itemConfirmButton.disabled = true;
    itemConfirmStatus.textContent = removal.kind === "closure" ? "Removing closure…" : "Deleting event…";
    try {
      const resource = removal.kind === "closure" ? "calendar-closures" : "events";
      await fetchJSON(`${apiBase}/admin/${resource}/${encodeURIComponent(removal.id)}`, {
        method: "DELETE",
      });
      pendingRemoval = null;
      itemConfirmDialog.close();
      if (removal.kind === "closure") {
        await Promise.all([loadCalendarClosures(), loadFacilityCalendar()]);
      } else {
        await loadFacilityEvents();
      }
    } catch (error) {
      itemConfirmStatus.textContent = error.message;
    } finally {
      itemConfirmButton.disabled = false;
    }
  }

  function facilityDateOffset(days = 0) {
    return new Date(Date.now() + 330 * 60 * 1000 + days * 86400000).toISOString().slice(0, 10);
  }

  async function fetchJSON(url, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    const isAdminMutation = url.includes(`${apiBase}/admin/`)
      && !["GET", "HEAD", "OPTIONS"].includes(method)
      && !url.endsWith("/admin/login");
    const headers = new Headers(options.headers || {});
    if (isAdminMutation) {
      if (!csrfToken) throw new Error("Your staff session expired. Sign in again.");
      headers.set("X-CSRF-Token", csrfToken);
    }
    const response = await fetch(url, {
      ...options,
      headers,
      credentials: "same-origin",
    });
    const payload = await response.json();
    if (response.status === 401 && csrfToken && isAdminMutation) {
      csrfToken = "";
      clearTimeout(inactivityTimer);
      bookings = [];
      showDashboard(false);
      loginStatus.textContent = "Your staff session expired. Sign in again.";
    }
    if (!response.ok) throw new Error(payload.error || "The admin request could not be completed.");
    return payload;
  }

  function scheduleInactivityLogout() {
    clearTimeout(inactivityTimer);
    if (!csrfToken) return;
    inactivityTimer = window.setTimeout(() => {
      void logoutAdmin("You were signed out after 15 minutes of inactivity.");
    }, inactivityTimeoutMs);
  }

  async function logoutAdmin(message) {
    if (!csrfToken) return;
    try {
      await fetchJSON(`${apiBase}/admin/logout`, { method: "POST" });
      csrfToken = "";
      clearTimeout(inactivityTimer);
      bookings = [];
      renderStats();
      renderBookings();
      showDashboard(false);
      loginStatus.textContent = message;
    } catch (error) {
      dashboardStatus.textContent = error.message;
    }
  }

  function showDashboard(authenticated) {
    loginPanel.hidden = authenticated;
    dashboard.hidden = !authenticated;
    showDashboardHome();
  }

  function renderStats() {
    const currentDate = new Date();
    const today = `${currentDate.getFullYear()}-${String(currentDate.getMonth() + 1).padStart(2, "0")}-${String(currentDate.getDate()).padStart(2, "0")}`;
    const active = bookings.filter(booking => booking.status !== "cancelled");
    const upcoming = active.reduce((count, booking) => count + booking.slots.filter(slot => slot.date >= today).length, 0);
    const metrics = [
      ["Confirmed bookings", bookings.filter(booking => booking.status === "confirmed").length],
      ["Pending review", bookings.filter(booking => booking.status === "pending").length],
      ["Upcoming sessions", upcoming],
      ["Cancelled bookings", bookings.filter(booking => booking.status === "cancelled").length],
      ["Total bookings", bookings.length],
    ];
    adminPortal.querySelector("#admin-stats").innerHTML = metrics.map(([label, value]) =>
      `<article class="admin-stat-card"><span>${label}</span><strong>${value}</strong></article>`
    ).join("");
  }

  function renderBookings() {
    const query = searchInput.value.trim().toLowerCase();
    const filter = statusFilter.value;
    const visible = bookings.filter(booking => {
      const searchable = `${booking.id} ${booking.userName} ${booking.piName} ${booking.email} ${booking.department}`.toLowerCase();
      return (!query || searchable.includes(query)) && (filter === "all" || booking.status === filter);
    });

    if (!visible.length) {
      bookingList.innerHTML = `<div class="admin-empty">${bookings.length ? "No bookings match these filters." : "No bookings have been submitted yet."}</div>`;
      return;
    }
    bookingList.innerHTML = visible.map(booking => {
      const sessions = booking.slots.map(slot =>
        `<span class="admin-session-chip" data-instrument-color="${escapeHTML(slot.color || "gray")}"><strong>${escapeHTML(slot.instrument)}</strong><small>${escapeHTML(formatDate(slot.date))} · ${escapeHTML(slot.time.replace("-", " – "))}</small></span>`
      ).join("");
      return `<article class="admin-booking-card">
        <div class="admin-booking-card-top"><div><span class="admin-booking-id">${escapeHTML(booking.id)}</span><h3>${escapeHTML(booking.userName)}</h3><span class="admin-booking-subtitle">PI: ${escapeHTML(booking.piName)} · ${escapeHTML(booking.department || "Department not provided")}</span></div><span class="admin-status-badge ${escapeHTML(booking.status)}">${escapeHTML(booking.status)}</span></div>
        <div class="admin-booking-card-meta"><a href="mailto:${escapeHTML(booking.email)}">${escapeHTML(booking.email)}</a><a href="tel:${escapeHTML(booking.phone)}">${escapeHTML(booking.phone)}</a><span>${escapeHTML(booking.specimen)}</span><span>${booking.slots.length} session${booking.slots.length === 1 ? "" : "s"}</span></div>
        <div class="admin-session-list">${sessions}</div>
        <div class="admin-booking-actions"><button class="admin-detail-button" type="button" data-booking-detail="${escapeHTML(booking.id)}">View details</button>${booking.hasForm
          ? `<a class="admin-detail-button" href="${apiBase}/admin/bookings/${encodeURIComponent(booking.id)}/form" target="_blank" rel="noreferrer">Download user form</a>`
          : ""}
          <button class="admin-detail-button" type="button" data-booking-edit="${escapeHTML(booking.id)}">Edit booking</button>
          ${booking.status === "pending"
          ? `<button class="admin-restore-button" type="button" data-booking-status="confirmed" data-booking-id="${escapeHTML(booking.id)}">Accept request</button><button class="admin-cancel-button" type="button" data-booking-status="cancelled" data-booking-id="${escapeHTML(booking.id)}">Decline request</button>`
          : booking.status === "confirmed"
            ? `<button class="admin-cancel-button" type="button" data-booking-status="cancelled" data-booking-id="${escapeHTML(booking.id)}">Cancel booking</button>`
            : `<button class="admin-restore-button" type="button" data-booking-status="confirmed" data-booking-id="${escapeHTML(booking.id)}">Restore booking</button>`}
          <button class="admin-delete-button" type="button" data-booking-delete="${escapeHTML(booking.id)}">Delete permanently</button></div>
      </article>`;
    }).join("");
  }

  function calendarDateKey(value) {
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  }

  function filteredCalendarEvents() {
    const instrument = calendarInstrumentFilter.value;
    return currentCalendarEvents.filter(event =>
      !instrument || !event.instrument || event.instrument === instrument
    );
  }

  function updateCalendarStatus() {
    const brownBearCount = currentCalendarEvents.filter(event => event.source === "calendar").length;
    const portalCount = currentCalendarEvents.filter(event => event.source === "portal").length;
    const closureCount = currentCalendarEvents.filter(event => event.source === "admin_closure").length;
    const filteredCount = filteredCalendarEvents().length;
    const instrument = calendarInstrumentFilter.value;
    const updated = calendarFetchedAt
      ? new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit" }).format(new Date(calendarFetchedAt))
      : "";
    calendarStatus.textContent = `${brownBearCount} Brown Bear events · ${portalCount} website sessions · ${closureCount} closure dates${instrument ? ` · Showing ${filteredCount} for ${instrument}` : ""}${updated ? ` · Synced ${updated}` : ""}`;
  }

  function renderCalendarEvents() {
    updateCalendarStatus();
    const month = calendarMonthInput.value;
    const [year, monthNumber] = month.split("-").map(Number);
    if (!Number.isInteger(year) || !Number.isInteger(monthNumber) || monthNumber < 1 || monthNumber > 12) {
      calendarEvents.innerHTML = '<div class="admin-empty">Choose a valid month to view its calendar.</div>';
      return;
    }
    const monthStart = new Date(year, monthNumber - 1, 1);
    const dayCount = new Date(year, monthNumber, 0).getDate();
    const days = [];
    for (let day = 1; day <= dayCount; day += 1) {
      const value = new Date(year, monthNumber - 1, day);
      if (value.getDay() !== 0 && value.getDay() !== 6) days.push(value);
    }
    if (!days.length) {
      calendarEvents.innerHTML = '<div class="admin-empty">No weekdays are available to display for this month.</div>';
      return;
    }
    const padStart = (monthStart.getDay() + 6) % 7;
    const padEnd = (5 - ((padStart + days.length) % 5)) % 5;
    const events = filteredCalendarEvents();
    const eventsByDate = new Map();
    events.forEach(event => {
      const dateEvents = eventsByDate.get(event.date) || [];
      dateEvents.push(event);
      eventsByDate.set(event.date, dateEvents);
    });
    if (!days.some(day => calendarDateKey(day) === selectedCalendarDate)) {
      const today = facilityDateOffset();
      selectedCalendarDate = days.some(day => calendarDateKey(day) === today)
        ? today
        : calendarDateKey(days[0]);
    }

    const cells = Array.from({ length: padStart }, () => '<span class="admin-calendar-empty-day" aria-hidden="true"></span>');
    days.forEach(day => {
      const date = calendarDateKey(day);
      const dayEvents = eventsByDate.get(date) || [];
      const colorDots = [...new Set(dayEvents.map(event => event.color || "neutral"))].slice(0, 4)
        .map(color => `<i class="admin-calendar-dot" data-instrument-color="${escapeHTML(color)}" aria-hidden="true"></i>`).join("");
      const previews = dayEvents.slice(0, 2).map(event => `
        <span class="admin-calendar-mini-event ${event.source === "portal" ? "portal" : event.source === "admin_closure" ? escapeHTML(event.eventType) : "brown-bear"}" data-instrument-color="${escapeHTML(event.color || "neutral")}" title="${escapeHTML(`${event.time || "Time not listed"} · ${event.instrument || event.eventType || "Unassigned instrument"} · ${event.title || "Facility calendar event"}`)}">
          <span>${escapeHTML((event.time || "").split(" - ")[0] || "All day")}</span> ${escapeHTML(event.instrument || event.title || "Facility event")}
        </span>`).join("");
      const more = dayEvents.length > 2 ? `<span class="admin-calendar-more">+${dayEvents.length - 2} more</span>` : "";
      const ariaLabel = `${formatDate(date)}, ${dayEvents.length} event${dayEvents.length === 1 ? "" : "s"}`;
      cells.push(`<button class="admin-calendar-day${date === selectedCalendarDate ? " selected" : ""}${date === facilityDateOffset() ? " today" : ""}" type="button" data-calendar-date="${date}" aria-label="${escapeHTML(ariaLabel)}" aria-pressed="${date === selectedCalendarDate}">
        <span class="admin-calendar-day-top"><strong>${day.getDate()}</strong><span class="admin-calendar-dots">${colorDots}</span></span>
        <span class="admin-calendar-day-count">${dayEvents.length ? `${dayEvents.length} event${dayEvents.length === 1 ? "" : "s"}` : "—"}</span>
        <span class="admin-calendar-day-preview">${previews}${more}</span>
      </button>`);
    });
    cells.push(...Array.from({ length: padEnd }, () => '<span class="admin-calendar-empty-day" aria-hidden="true"></span>'));

    const selectedEvents = eventsByDate.get(selectedCalendarDate) || [];
    const filterLabel = calendarInstrumentFilter.value || "all instruments";
    calendarEvents.innerHTML = `
      <div class="admin-calendar-grid" role="group" aria-label="${escapeHTML(new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric" }).format(monthStart))}">
        ${["Mon", "Tue", "Wed", "Thu", "Fri"].map(day => `<span class="admin-calendar-weekday">${day}</span>`).join("")}
        ${cells.join("")}
      </div>
      <section class="admin-calendar-agenda" aria-labelledby="admin-calendar-agenda-title">
        <div class="admin-calendar-agenda-heading"><div><span class="eyebrow">SELECTED DAY</span><h4 id="admin-calendar-agenda-title">${escapeHTML(formatDate(selectedCalendarDate))}</h4></div><span class="admin-calendar-agenda-count">${selectedEvents.length} ${selectedEvents.length === 1 ? "event" : "events"}</span></div>
        ${selectedEvents.length ? `<div class="admin-calendar-agenda-list">${selectedEvents.map(event => `
          <article class="admin-agenda-event ${event.source === "portal" ? "portal" : event.source === "admin_closure" ? escapeHTML(event.eventType) : "brown-bear"}" data-instrument-color="${escapeHTML(event.color || "neutral")}">
            <time>${escapeHTML(event.time || "Time not listed")}</time><span class="admin-agenda-event-color" aria-hidden="true"></span>
            <div class="admin-agenda-event-info"><strong>${escapeHTML(event.title || "Facility calendar event")}</strong><small>${event.source === "portal" ? `${escapeHTML(event.instrument)} · Website booking` : event.source === "admin_closure" ? `${event.eventType === "exception" ? "Exception holiday" : "Workshop holiday"} · Staff-managed` : `${escapeHTML(event.instrument || "Unassigned instrument")} · Brown Bear · managed externally`}</small></div>
            ${event.source === "portal" && event.bookingId ? `<div class="admin-agenda-actions"><button class="admin-detail-button" type="button" data-booking-edit="${escapeHTML(event.bookingId)}">Edit</button><button class="admin-delete-button" type="button" data-booking-delete="${escapeHTML(event.bookingId)}">Delete</button></div>` : event.source === "admin_closure" && event.closureId ? `<button class="admin-delete-button" type="button" data-calendar-closure-delete="${escapeHTML(event.closureId)}">Remove</button>` : '<span class="admin-external-badge">External</span>'}
          </article>`).join("")}</div>` : `<div class="admin-calendar-day-empty">No events for ${escapeHTML(filterLabel)} on this day.</div>`}
      </section>`;
  }

  async function loadFacilityCalendar() {
    const requestId = ++calendarRequestId;
    const month = calendarMonthInput.value;
    if (!/^\d{4}-\d{2}$/.test(month)) {
      calendarStatus.textContent = "Choose a valid calendar month.";
      return;
    }
    calendarStatus.textContent = "Syncing Brown Bear and website bookings…";
    calendarEvents.innerHTML = '<div class="admin-empty">Loading the selected month…</div>';
    try {
      const payload = await fetchJSON(`${apiBase}/admin/calendar?month=${encodeURIComponent(month)}`, { cache: "no-store" });
      if (requestId !== calendarRequestId) return;
      currentCalendarEvents = payload.events;
      calendarFetchedAt = payload.fetchedAt;
      renderCalendarEvents();
      brownBearAdminLink.href = payload.brownBearAdminUrl;
    } catch (error) {
      if (requestId !== calendarRequestId) return;
      calendarFetchedAt = "";
      calendarStatus.textContent = error.message;
      currentCalendarEvents = [];
      calendarEvents.innerHTML = '<div class="admin-empty">Calendar sync failed. Refresh to try again; Brown Bear entries are not editable in this portal.</div>';
    }
  }

  async function loadBookings() {
    dashboardStatus.textContent = "Loading bookings…";
    const payload = await fetchJSON(`${apiBase}/admin/bookings`, { cache: "no-store" });
    bookings = payload.bookings;
    renderStats();
    renderBookings();
    dashboardStatus.textContent = `${bookings.length} booking${bookings.length === 1 ? "" : "s"} · Updated ${new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit" }).format(new Date())}`;
  }

  function renderCalendarClosures() {
    if (!calendarClosures.length) {
      closureList.innerHTML = '<p class="admin-status">No upcoming staff-managed closures.</p>';
      return;
    }
    closureList.innerHTML = calendarClosures.map(closure => {
      const dates = closure.startDate === closure.endDate
        ? formatDate(closure.startDate)
        : `${formatDate(closure.startDate)} – ${formatDate(closure.endDate)}`;
      const times = closure.slotTimes.length
        ? closure.slotTimes.map(formatTimeSlot).join(", ")
        : "All sessions";
      const label = closure.type === "exception" ? "Exception holiday" : "Workshop holiday";
      return `<article class="admin-closure-item ${escapeHTML(closure.type)}">
        <div><span>${escapeHTML(label)} · ${escapeHTML(dates)} · ${escapeHTML(times)}</span><strong>${escapeHTML(closure.remark)}</strong></div>
        <button class="admin-delete-button" type="button" data-closure-delete="${escapeHTML(closure.id)}">Remove</button>
      </article>`;
    }).join("");
  }

  async function loadCalendarClosures() {
    const payload = await fetchJSON(`${apiBase}/admin/calendar-closures`, { cache: "no-store" });
    calendarClosures = payload.closures;
    renderCalendarClosures();
  }

  function renderFacilityEvents() {
    if (!facilityEvents.length) {
      eventList.innerHTML = '<p class="admin-status">No events have been added yet.</p>';
      return;
    }
    eventList.innerHTML = facilityEvents.map(item => {
      const category = item.category === "workshop" ? "Workshop" : "Facility event";
      const dates = item.startDate === item.endDate
        ? formatDate(item.startDate)
        : `${formatDate(item.startDate)} – ${formatDate(item.endDate)}`;
      const status = item.endDate < facilityDateOffset() ? "Past" : "Upcoming";
      return `<article class="admin-event-card ${escapeHTML(item.category)}">
        <div class="admin-event-card-meta"><span>${escapeHTML(category)}</span><span>${escapeHTML(status)} · ${escapeHTML(dates)}</span></div>
        <h5>${escapeHTML(item.title)}</h5>
        <p>${escapeHTML(item.summary)}</p>
        <div class="admin-event-card-link"><a href="${escapeHTML(item.linkUrl)}" target="_blank" rel="noopener noreferrer">${escapeHTML(item.linkLabel)} ↗</a></div>
        <div class="admin-event-card-actions"><button class="admin-detail-button" type="button" data-event-edit="${escapeHTML(item.id)}">Edit details</button><button class="admin-delete-button" type="button" data-event-delete="${escapeHTML(item.id)}">Delete</button></div>
      </article>`;
    }).join("");
  }

  async function loadFacilityEvents() {
    const payload = await fetchJSON(`${apiBase}/admin/events`, { cache: "no-store" });
    facilityEvents = payload.events;
    renderFacilityEvents();
  }

  function renderWorkshopContentItem(item, archive = false) {
    const dates = archive ? "Past workshop" : `${formatDate(item.startDate)}${item.endDate === item.startDate ? "" : ` – ${formatDate(item.endDate)}`}`;
    const preview = item.imageUrl
      ? `<img class="admin-workshop-photo-preview" src="${escapeHTML(item.imageUrl)}" alt="${escapeHTML(item.title)} photo" loading="lazy">`
      : '<div class="admin-workshop-photo-empty">No photo uploaded</div>';
    return `<article class="admin-workshop-content-card">
      <div class="admin-workshop-content-heading">${preview}<div><span class="eyebrow">${escapeHTML(dates)}</span><h4>${escapeHTML(item.title)}</h4></div></div>
      <form class="admin-workshop-content-form" data-workshop-content-form="${archive ? "archive" : escapeHTML(item.id)}">
        <label>Event or workshop summary<textarea name="summary" maxlength="240" rows="3" required>${escapeHTML(item.summary)}</textarea></label>
        <label>Photo<input type="file" name="photo" accept="image/jpeg,image/png,image/webp"><small>JPEG, PNG, or WebP. Maximum 5 MB.</small></label>
        ${item.imageUrl ? '<label class="admin-workshop-remove-photo"><input type="checkbox" name="removePhoto" value="true"> Remove current photo</label>' : ""}
        <p class="admin-status" data-workshop-content-status role="status" aria-live="polite"></p>
        <button class="btn primary" type="submit">Save workshop content</button>
      </form>
    </article>`;
  }

  function renderWorkshopContent() {
    const content = [];
    if (workshopArchive) content.push(renderWorkshopContentItem(workshopArchive, true));
    content.push(...eventContentItems.map(item => renderWorkshopContentItem(item)));
    workshopContentList.innerHTML = content.length
      ? content.join("")
      : '<p class="admin-status">No published workshops are available to edit.</p>';
  }

  async function loadWorkshopContent() {
    workshopContentStatus.textContent = "Loading workshop content…";
    try {
      const payload = await fetchJSON(`${apiBase}/admin/workshop-content`, { cache: "no-store" });
      workshopArchive = payload.archive;
      eventContentItems = payload.events;
      renderWorkshopContent();
      workshopContentStatus.textContent = "";
    } catch (error) {
      workshopContentStatus.textContent = error.message;
    }
  }

  workshopContentList.addEventListener("submit", async event => {
    const form = event.target.closest("[data-workshop-content-form]");
    if (!form) return;
    event.preventDefault();
    if (!form.reportValidity()) return;
    const submitButton = form.querySelector('[type="submit"]');
    const status = form.querySelector("[data-workshop-content-status]");
    const target = form.dataset.workshopContentForm;
    submitButton.disabled = true;
    status.textContent = "Saving workshop content…";
    try {
      const payload = await fetchJSON(target === "archive"
        ? `${apiBase}/admin/workshop-content/archive`
        : `${apiBase}/admin/workshop-content/${encodeURIComponent(target)}`, {
        method: "PUT",
        body: new FormData(form),
      });
      await loadWorkshopContent();
      dashboardStatus.textContent = payload.warning
        || "Event or workshop summary and photo updated on the public website.";
      void loadFacilityEvents().catch(error => {
        dashboardStatus.textContent = `Content was saved, but the event list could not refresh: ${error.message}`;
      });
    } catch (error) {
      status.textContent = error.message;
    } finally {
      submitButton.disabled = false;
    }
  });

  adminPortal.querySelector("#admin-workshop-content-refresh").addEventListener("click", () => {
    void loadWorkshopContent();
  });

  function resetFacilityEventForm() {
    eventForm.reset();
    eventForm.elements.eventId.value = "";
    eventFormTitle.textContent = "Create an event";
    eventForm.querySelector('[type="submit"]').textContent = "Publish event";
    eventCancelEditButton.hidden = true;
    eventFormStatus.textContent = "";
  }

  function editFacilityEvent(id) {
    const item = facilityEvents.find(facilityEvent => facilityEvent.id === id);
    if (!item) {
      dashboardStatus.textContent = "This event is no longer in the list. Refresh and try again.";
      return;
    }
    for (const [field, value] of Object.entries({
      eventId: item.id,
      category: item.category,
      title: item.title,
      startDate: item.startDate,
      endDate: item.endDate,
      summary: item.summary,
      description: item.description,
      linkLabel: item.linkLabel,
      linkUrl: item.linkUrl,
    })) eventForm.elements[field].value = value;
    eventFormTitle.textContent = `Edit ${item.category === "workshop" ? "workshop" : "facility event"}`;
    eventForm.querySelector('[type="submit"]').textContent = "Save event changes";
    eventCancelEditButton.hidden = false;
    eventFormStatus.textContent = "";
    eventForm.scrollIntoView({ behavior: "smooth", block: "center" });
    eventForm.elements.title.focus({ preventScroll: true });
  }

  eventForm.addEventListener("submit", async event => {
    event.preventDefault();
    if (!eventForm.reportValidity()) return;
    const values = new FormData(eventForm);
    const startDate = values.get("startDate");
    const endDate = values.get("endDate");
    if (endDate < startDate) {
      eventForm.elements.endDate.setCustomValidity("Choose an end date on or after the start date.");
      eventForm.elements.endDate.reportValidity();
      eventForm.elements.endDate.setCustomValidity("");
      return;
    }
    const eventId = values.get("eventId");
    const submitButton = eventForm.querySelector('[type="submit"]');
    const eventPayload = {
      category: values.get("category"),
      title: values.get("title"),
      startDate,
      endDate,
      summary: values.get("summary"),
      description: values.get("description"),
      linkLabel: values.get("linkLabel"),
      linkUrl: values.get("linkUrl"),
    };
    submitButton.disabled = true;
    eventFormStatus.textContent = eventId ? "Saving event changes…" : "Publishing event…";
    try {
      await fetchJSON(eventId
        ? `${apiBase}/admin/events/${encodeURIComponent(eventId)}`
        : `${apiBase}/admin/events`, {
        method: eventId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(eventPayload),
      });
      resetFacilityEventForm();
      await loadFacilityEvents();
      dashboardStatus.textContent = "Event content updated on the homepage and Events & Workshop page.";
    } catch (error) {
      eventFormStatus.textContent = error.message;
    } finally {
      submitButton.disabled = false;
    }
  });

  eventCancelEditButton.addEventListener("click", resetFacilityEventForm);
  eventList.addEventListener("click", event => {
    const editButton = event.target.closest("[data-event-edit]");
    if (editButton) {
      editFacilityEvent(editButton.dataset.eventEdit);
      return;
    }
    const deleteButton = event.target.closest("[data-event-delete]");
    if (deleteButton) requestManagedItemRemoval("event", deleteButton.dataset.eventDelete);
  });
  adminPortal.querySelector("#admin-event-refresh").addEventListener("click", async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await loadFacilityEvents();
    } catch (error) {
      eventList.innerHTML = `<p class="admin-status">${escapeHTML(error.message)}</p>`;
    } finally {
      button.disabled = false;
    }
  });

  async function loadDashboard() {
    const [bookingResult, calendarResult, instrumentsResult, closuresResult, eventsResult] = await Promise.allSettled([
      loadBookings(),
      loadFacilityCalendar(),
      fetchJSON(`${apiBase}/instruments`, { cache: "no-store" }),
      loadCalendarClosures(),
      loadFacilityEvents(),
    ]);
    if (instrumentsResult.status === "fulfilled") {
      instruments = instrumentsResult.value;
      const selectedInstrument = calendarInstrumentFilter.value;
      calendarInstrumentFilter.innerHTML = '<option value="">All instruments</option>' + instruments.map(instrument =>
        `<option value="${escapeHTML(instrument.name)}">${escapeHTML(instrument.name)}</option>`
      ).join("");
      calendarInstrumentFilter.value = selectedInstrument;
      renderCalendarEvents();
    }
    else dashboardStatus.textContent = `Instrument options could not be loaded: ${instrumentsResult.reason.message}`;
    if (bookingResult.status === "rejected") dashboardStatus.textContent = bookingResult.reason.message;
    if (calendarResult.status === "rejected") calendarStatus.textContent = calendarResult.reason.message;
    if (closuresResult.status === "rejected") closureList.innerHTML = `<p class="admin-status">${escapeHTML(closuresResult.reason.message)}</p>`;
    if (eventsResult.status === "rejected") eventList.innerHTML = `<p class="admin-status">${escapeHTML(eventsResult.reason.message)}</p>`;
  }

  async function checkSession() {
    try {
      const payload = await fetchJSON(`${apiBase}/admin/session`, { cache: "no-store" });
      if (payload.authenticated && payload.csrfToken) {
        csrfToken = payload.csrfToken;
        await fetchJSON(`${apiBase}/admin/logout`, { method: "POST" });
      }
      csrfToken = "";
      showDashboard(false);
      loginStatus.textContent = "Sign in to start a new staff session.";
    } catch (error) {
      loginStatus.textContent = error.message;
      showDashboard(false);
    }
  }

  loginForm.addEventListener("submit", async event => {
    event.preventDefault();
    loginStatus.textContent = "";
    const submitButton = loginForm.querySelector('[type="submit"]');
    submitButton.disabled = true;
    try {
      const payload = await fetchJSON(`${apiBase}/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: loginForm.elements.password.value }),
      });
      csrfToken = payload.csrfToken || "";
      if (!csrfToken) throw new Error("A secure staff session could not be started. Contact the administrator.");
      loginForm.reset();
      showDashboard(true);
      scheduleInactivityLogout();
      await loadDashboard();
    } catch (error) {
      loginStatus.textContent = error.message;
    } finally {
      submitButton.disabled = false;
    }
  });

  adminPortal.querySelector("#admin-logout").addEventListener("click", async () => {
    await logoutAdmin("You have been signed out.");
  });

  for (const eventName of ["pointerdown", "keydown", "touchstart", "click"]) {
    window.addEventListener(eventName, scheduleInactivityLogout, { passive: true });
  }
  window.addEventListener("pagehide", () => {
    if (!csrfToken) return;
    const headers = new Headers({ "X-CSRF-Token": csrfToken });
    void fetch(`${apiBase}/admin/logout`, {
      method: "POST",
      headers,
      credentials: "same-origin",
      keepalive: true,
    }).catch(() => {});
    csrfToken = "";
    clearTimeout(inactivityTimer);
  });

  adminPortal.querySelector("#admin-refresh").addEventListener("click", () => {
    void loadDashboard().catch(error => { dashboardStatus.textContent = error.message; });
  });
  adminPortal.querySelector("#admin-calendar-refresh").addEventListener("click", () => {
    void loadFacilityCalendar();
  });
  adminPortal.querySelector("#admin-calendar-previous").addEventListener("click", () => {
    moveCalendarMonth(-1);
  });
  adminPortal.querySelector("#admin-calendar-next").addEventListener("click", () => {
    moveCalendarMonth(1);
  });
  calendarInstrumentFilter.addEventListener("change", renderCalendarEvents);
  calendarMonthInput.addEventListener("change", () => {
    void loadFacilityCalendar();
  });
  searchInput.addEventListener("input", renderBookings);
  statusFilter.addEventListener("change", renderBookings);

  function moveCalendarMonth(offset) {
    const values = calendarMonthInput.value.split("-").map(Number);
    const validMonth = values.length === 2 && Number.isInteger(values[0]) &&
      Number.isInteger(values[1]) && values[1] >= 1 && values[1] <= 12;
    const [year, month] = validMonth
      ? values
      : [new Date().getFullYear(), new Date().getMonth() + 1];
    const next = new Date(year, month - 1 + offset, 1);
    calendarMonthInput.value = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
    selectedCalendarDate = "";
    void loadFacilityCalendar();
  }

  async function deleteBooking(bookingId, deleteButton) {
    const booking = bookings.find(item => item.id === bookingId);
    if (!booking || !window.confirm(`Permanently delete booking ${booking.id}${booking.hasForm ? " and its uploaded user form" : ""}? This cannot be undone.`)) return;
    deleteButton.disabled = true;
    try {
      const payload = await fetchJSON(`${apiBase}/admin/bookings/${encodeURIComponent(booking.id)}`, {
        method: "DELETE",
      });
      bookings = bookings.filter(item => item.id !== booking.id);
      renderStats();
      renderBookings();
      await loadFacilityCalendar();
      dashboardStatus.textContent = payload.formDeleted
        ? `Booking ${booking.id} and its uploaded form were deleted.`
        : `Booking ${booking.id} was deleted, but its uploaded form could not be removed. Contact the administrator.`;
    } catch (error) {
      dashboardStatus.textContent = error.message;
      deleteButton.disabled = false;
    }
  }

  function appendEditSlot(slot = {}) {
    if (editSlots.querySelectorAll("[data-edit-slot]").length >= 12) {
      editStatus.textContent = "A booking can contain up to 12 sessions.";
      return;
    }
    const index = editSlots.querySelectorAll("[data-edit-slot]").length + 1;
    const instrumentOptions = instruments.map(instrument =>
      `<option value="${escapeHTML(instrument.name)}">${escapeHTML(instrument.name)}</option>`
    ).join("");
    const minDate = nextBusinessDate();
    editSlots.insertAdjacentHTML("beforeend", `
      <fieldset class="admin-edit-slot" data-edit-slot>
        <legend>Session ${index}</legend>
        <label>Instrument<select name="instrument" required>${instrumentOptions}</select></label>
        <label>Date<input name="date" type="date" min="${minDate}" max="${facilityDateOffset(90)}" required value="${escapeHTML(slot.date || minDate)}"></label>
        <label>Time<select name="time" required>${bookingTimes.map(time =>
          `<option value="${time}">${formatTimeSlot(time)}</option>`
        ).join("")}</select></label>
        <button class="admin-delete-button" type="button" data-remove-session>Remove session</button>
      </fieldset>`);
    const row = editSlots.lastElementChild;
    if (slot.instrument) row.querySelector('[name="instrument"]').value = slot.instrument;
    if (slot.time) row.querySelector('[name="time"]').value = slot.time;
    const dateInput = row.querySelector('[name="date"]');
    dateInput.addEventListener("change", () => {
      const weekday = new Date(`${dateInput.value}T12:00:00`).getDay();
      dateInput.setCustomValidity(weekday === 0 || weekday === 6
        ? "Choose a weekday; weekend sessions are not available."
        : "");
    });
    editStatus.textContent = "";
  }

  function nextBusinessDate() {
    let offset = 1;
    let date = new Date(`${facilityDateOffset(offset)}T00:00:00Z`);
    while (date.getUTCDay() === 0 || date.getUTCDay() === 6) {
      offset += 1;
      date = new Date(`${facilityDateOffset(offset)}T00:00:00Z`);
    }
    return date.toISOString().slice(0, 10);
  }

  function openEditDialog(booking = null) {
    editingBookingId = booking?.id || "";
    creatingBooking = !booking;
    document.querySelector("#admin-edit-title").textContent =
      booking ? `Edit booking · ${booking.id}` : "Add a booking";
    editForm.querySelector('[type="submit"]').textContent =
      booking ? "Save booking" : "Create confirmed booking";
    editStatus.textContent = "";
    for (const [name, value] of Object.entries({
      userName: booking?.userName || "",
      piName: booking?.piName || "",
      email: booking?.email || "",
      phone: booking?.phone || "",
      department: booking?.department || "",
      specimen: booking?.specimen || "",
      notes: booking?.notes || "",
    })) editForm.elements[name].value = value;
    editSlots.replaceChildren();
    (booking?.slots || [{}]).forEach(appendEditSlot);
    editDialog.showModal();
  }

  editForm.addEventListener("submit", async event => {
    event.preventDefault();
    if (!editForm.reportValidity()) return;
    const slots = [...editSlots.querySelectorAll("[data-edit-slot]")].map(row => ({
      instrument: row.querySelector('[name="instrument"]').value,
      date: row.querySelector('[name="date"]').value,
      time: row.querySelector('[name="time"]').value,
    }));
    const submitButton = editForm.querySelector('[type="submit"]');
    submitButton.disabled = true;
    editStatus.textContent = "Checking live conflicts and saving…";
    try {
      const details = Object.fromEntries(
        ["userName", "piName", "email", "phone", "department", "specimen", "notes"]
          .map(name => [name, editForm.elements[name].value.trim()])
      );
      const payload = await fetchJSON(
        creatingBooking
          ? `${apiBase}/admin/bookings`
          : `${apiBase}/admin/bookings/${encodeURIComponent(editingBookingId)}`,
        {
        method: creatingBooking ? "POST" : "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...details, slots }),
      });
      if (creatingBooking) bookings.unshift(payload.booking);
      else bookings = bookings.map(booking => booking.id === editingBookingId ? payload.booking : booking);
      const savedId = payload.booking.id;
      editDialog.close();
      renderStats();
      renderBookings();
      await loadFacilityCalendar();
      dashboardStatus.textContent = creatingBooking
        ? `Booking ${savedId} created.${payload.notification?.sent ? " Confirmation email sent." : ` Email not sent: ${payload.notification?.error || "delivery status unavailable"}`}`
        : `Booking ${savedId} updated.`;
    } catch (error) {
      editStatus.textContent = error.message;
    } finally {
      submitButton.disabled = false;
    }
  });

  document.querySelector("#admin-add-session").addEventListener("click", () => appendEditSlot());
  editSlots.addEventListener("click", event => {
    const removeButton = event.target.closest("[data-remove-session]");
    if (!removeButton) return;
    if (editSlots.querySelectorAll("[data-edit-slot]").length <= 1) {
      editStatus.textContent = "Keep at least one session in the booking.";
      return;
    }
    removeButton.closest("[data-edit-slot]").remove();
    [...editSlots.querySelectorAll("[data-edit-slot] legend")].forEach((legend, index) => {
      legend.textContent = `Session ${index + 1}`;
    });
  });
  adminPortal.querySelector("#admin-create-booking").addEventListener("click", () => openEditDialog());

  document.querySelectorAll("[data-close-admin-edit]").forEach(button =>
    button.addEventListener("click", () => editDialog.close())
  );
  editDialog.addEventListener("click", event => {
    if (event.target === editDialog) editDialog.close();
  });
  calendarEvents.addEventListener("click", event => {
    const dayButton = event.target.closest("[data-calendar-date]");
    if (dayButton) {
      selectedCalendarDate = dayButton.dataset.calendarDate;
      renderCalendarEvents();
      return;
    }
    const editButton = event.target.closest("[data-booking-edit]");
    if (editButton) {
      const booking = bookings.find(item => item.id === editButton.dataset.bookingEdit);
      if (booking) openEditDialog(booking);
      return;
    }
    const deleteButton = event.target.closest("[data-booking-delete]");
    if (deleteButton) {
      void deleteBooking(deleteButton.dataset.bookingDelete, deleteButton);
      return;
    }
    const closureDeleteButton = event.target.closest("[data-calendar-closure-delete]");
    if (closureDeleteButton) {
      requestManagedItemRemoval("closure", closureDeleteButton.dataset.calendarClosureDelete);
    }
  });

  bookingList.addEventListener("click", async event => {
    const editButton = event.target.closest("[data-booking-edit]");
    if (editButton) {
      const booking = bookings.find(item => item.id === editButton.dataset.bookingEdit);
      if (booking) openEditDialog(booking);
      return;
    }
    const deleteButton = event.target.closest("[data-booking-delete]");
    if (deleteButton) {
      void deleteBooking(deleteButton.dataset.bookingDelete, deleteButton);
      return;
    }
    const detailButton = event.target.closest("[data-booking-detail]");
    if (detailButton) {
      const booking = bookings.find(item => item.id === detailButton.dataset.bookingDetail);
      if (!booking) return;
      document.querySelector("#admin-detail-title").textContent = booking.id;
      detailContent.innerHTML = `
        <dl class="admin-detail-grid">
          <div><dt>Student / user</dt><dd>${escapeHTML(booking.userName)}</dd></div>
          <div><dt>Principal investigator</dt><dd>${escapeHTML(booking.piName)}</dd></div>
          <div><dt>Email</dt><dd>${escapeHTML(booking.email)}</dd></div>
          <div><dt>Phone</dt><dd>${escapeHTML(booking.phone)}</dd></div>
          <div><dt>Department / institution</dt><dd>${escapeHTML(booking.department || "Not provided")}</dd></div>
          <div><dt>Sample type</dt><dd>${escapeHTML(booking.specimen)}</dd></div>
          <div><dt>Status</dt><dd>${escapeHTML(booking.status)}</dd></div>
          <div><dt>Submitted</dt><dd>${escapeHTML(new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(booking.createdAt)))}</dd></div>
          <div class="wide"><dt>Experiment notes</dt><dd>${escapeHTML(booking.notes || "No notes provided")}</dd></div>
          <div class="wide"><dt>Selected sessions</dt><dd class="admin-detail-sessions">${booking.slots.map(slot => `<span data-instrument-color="${escapeHTML(slot.color || "gray")}">${escapeHTML(slot.instrument)} · ${escapeHTML(formatDate(slot.date))} · ${escapeHTML(slot.time.replace("-", " – "))}</span>`).join("")}</dd></div>
        </dl>${booking.hasForm
          ? `<a class="btn primary admin-detail-download" href="${apiBase}/admin/bookings/${encodeURIComponent(booking.id)}/form" target="_blank" rel="noreferrer">Download ${escapeHTML(booking.formName)}</a>`
          : `<p class="admin-status">No user form was uploaded for this staff-created booking.</p>`}`;
      detailDialog.showModal();
      return;
    }
    const statusButton = event.target.closest("[data-booking-status]");
    if (!statusButton) return;
    statusButton.disabled = true;
    try {
      const bookingId = statusButton.dataset.bookingId;
      const payload = await fetchJSON(`${apiBase}/admin/bookings/${encodeURIComponent(bookingId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: statusButton.dataset.bookingStatus }),
      });
      bookings = bookings.map(booking => booking.id === bookingId ? payload.booking : booking);
      renderStats();
      renderBookings();
      await loadFacilityCalendar();
      dashboardStatus.textContent = payload.notification
        ? payload.notification.sent
          ? `Booking ${bookingId} accepted. Confirmation email sent.`
          : `Booking ${bookingId} accepted, but the confirmation email was not sent: ${payload.notification.error}`
        : `Booking ${bookingId} updated.`;
    } catch (error) {
      dashboardStatus.textContent = error.message;
      statusButton.disabled = false;
    }
  });

  document.querySelector("[data-close-admin-detail]").addEventListener("click", () => detailDialog.close());
  detailDialog.addEventListener("click", event => {
    if (event.target === detailDialog) detailDialog.close();
  });

  const today = facilityDateOffset();
  adminPortal.querySelectorAll("[data-closure-toggle]").forEach(toggle => {
    const form = adminPortal.querySelector(`[data-closure-form="${toggle.dataset.closureToggle}"]`);
    toggle.setAttribute("aria-expanded", "false");
    form.querySelectorAll('input[type="date"]').forEach(input => { input.min = today; });
    toggle.addEventListener("change", () => {
      form.hidden = !toggle.checked;
      toggle.setAttribute("aria-expanded", String(toggle.checked));
    });
    const scope = form.querySelector("[data-closure-scope]");
    const timesFieldset = form.querySelector("[data-closure-times]");
    scope.addEventListener("change", () => {
      timesFieldset.hidden = scope.value !== "specific";
      if (scope.value === "all") {
        timesFieldset.querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = false; });
      }
    });
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const status = form.querySelector("[data-closure-status]");
      const submitButton = form.querySelector('[type="submit"]');
      const slotTimes = scope.value === "specific"
        ? [...timesFieldset.querySelectorAll('input[type="checkbox"]:checked')].map(input => input.value)
        : [];
      if (scope.value === "specific" && !slotTimes.length) {
        status.textContent = "Select at least one time slot.";
        return;
      }
      const values = new FormData(form);
      status.textContent = "Saving closure…";
      submitButton.disabled = true;
      try {
        await fetchJSON(`${apiBase}/admin/calendar-closures`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            type: form.dataset.closureForm,
            startDate: values.get("startDate"),
            endDate: values.get("endDate"),
            scope: scope.value,
            slotTimes,
            remark: values.get("remark"),
          }),
        });
        form.reset();
        scope.dispatchEvent(new Event("change"));
        await Promise.all([loadCalendarClosures(), loadFacilityCalendar()]);
        status.textContent = "Closure saved and added to the public schedule.";
      } catch (error) {
        status.textContent = error.message;
      } finally {
        submitButton.disabled = false;
      }
    });
  });

  closureList.addEventListener("click", async event => {
    const button = event.target.closest("[data-closure-delete]");
    if (!button) return;
    requestManagedItemRemoval("closure", button.dataset.closureDelete);
  });

  itemConfirmButton.addEventListener("click", () => { void removeManagedItem(); });
  itemConfirmCancelButton.addEventListener("click", () => {
    pendingRemoval = null;
    itemConfirmDialog.close();
  });
  itemConfirmDialog.addEventListener("click", event => {
    if (event.target === itemConfirmDialog && !itemConfirmButton.disabled) {
      pendingRemoval = null;
      itemConfirmDialog.close();
    }
  });
  itemConfirmDialog.addEventListener("cancel", event => {
    if (itemConfirmButton.disabled) {
      event.preventDefault();
      return;
    }
    pendingRemoval = null;
  });

  const now = new Date();
  calendarMonthInput.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  void checkSession();
}
