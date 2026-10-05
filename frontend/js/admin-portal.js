const adminPortal = document.querySelector("[data-admin-portal]");

if (adminPortal) {
  const apiBase = window.location.protocol === "file:" ? "http://127.0.0.1:5000/api" : "/api";
  const loginPanel = adminPortal.querySelector("#admin-login-panel");
  const dashboard = adminPortal.querySelector("#admin-dashboard");
  const loginForm = adminPortal.querySelector("#admin-login-form");
  const loginStatus = adminPortal.querySelector("#admin-login-status");
  const dashboardStatus = adminPortal.querySelector("#admin-dashboard-status");
  const bookingList = adminPortal.querySelector("#admin-booking-list");
  const searchInput = adminPortal.querySelector("#admin-search");
  const statusFilter = adminPortal.querySelector("#admin-status-filter");
  const detailDialog = document.querySelector("#admin-booking-detail");
  const detailContent = document.querySelector("#admin-detail-content");
  const calendarMonthInput = adminPortal.querySelector("#admin-calendar-month");
  const calendarStatus = adminPortal.querySelector("#admin-calendar-status");
  const calendarEvents = adminPortal.querySelector("#admin-calendar-events");
  const calendarInstrumentFilter = adminPortal.querySelector("#admin-calendar-instrument");
  const brownBearAdminLink = adminPortal.querySelector("#admin-brownbear-admin");
  const editDialog = document.querySelector("#admin-edit-booking");
  const editForm = document.querySelector("#admin-edit-form");
  const editSlots = document.querySelector("#admin-edit-slots");
  const editStatus = document.querySelector("#admin-edit-status");
  const bookingTimes = ["10:00-11:00", "11:00-12:00", "12:00-13:00", "14:00-15:00", "15:00-16:00", "16:00-17:00"];
  let bookings = [];
  let instruments = [];
  let editingBookingId = "";
  let currentCalendarEvents = [];
  let calendarFetchedAt = "";
  let selectedCalendarDate = "";
  let calendarRequestId = 0;

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

  function facilityDateOffset(days = 0) {
    return new Date(Date.now() + 330 * 60 * 1000 + days * 86400000).toISOString().slice(0, 10);
  }

  async function fetchJSON(url, options = {}) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The admin request could not be completed.");
    return payload;
  }

  function showDashboard(authenticated) {
    loginPanel.hidden = authenticated;
    dashboard.hidden = !authenticated;
  }

  function renderStats() {
    const currentDate = new Date();
    const today = `${currentDate.getFullYear()}-${String(currentDate.getMonth() + 1).padStart(2, "0")}-${String(currentDate.getDate()).padStart(2, "0")}`;
    const active = bookings.filter(booking => booking.status === "confirmed");
    const upcoming = active.reduce((count, booking) => count + booking.slots.filter(slot => slot.date >= today).length, 0);
    const metrics = [
      ["Confirmed bookings", active.length],
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
        <div class="admin-booking-actions"><button class="admin-detail-button" type="button" data-booking-detail="${escapeHTML(booking.id)}">View details</button><a class="admin-detail-button" href="${apiBase}/admin/bookings/${encodeURIComponent(booking.id)}/form" target="_blank" rel="noreferrer">Download user form</a>${booking.status === "confirmed"
          ? `<button class="admin-detail-button" type="button" data-booking-edit="${escapeHTML(booking.id)}">Change sessions</button>`
          : ""}
          ${booking.status === "confirmed"
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
    return currentCalendarEvents.filter(event => !instrument || event.instrument === instrument);
  }

  function updateCalendarStatus() {
    const brownBearCount = currentCalendarEvents.filter(event => event.source === "calendar").length;
    const portalCount = currentCalendarEvents.filter(event => event.source === "portal").length;
    const filteredCount = filteredCalendarEvents().length;
    const instrument = calendarInstrumentFilter.value;
    const updated = calendarFetchedAt
      ? new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit" }).format(new Date(calendarFetchedAt))
      : "";
    calendarStatus.textContent = `${brownBearCount} Brown Bear events · ${portalCount} website sessions${instrument ? ` · Showing ${filteredCount} for ${instrument}` : ""}${updated ? ` · Synced ${updated}` : ""}`;
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
        <span class="admin-calendar-mini-event ${event.source === "portal" ? "portal" : "brown-bear"}" data-instrument-color="${escapeHTML(event.color || "neutral")}" title="${escapeHTML(`${event.time || "Time not listed"} · ${event.instrument || "Unassigned instrument"} · ${event.title || "Facility calendar event"}`)}">
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
          <article class="admin-agenda-event ${event.source === "portal" ? "portal" : "brown-bear"}" data-instrument-color="${escapeHTML(event.color || "neutral")}">
            <time>${escapeHTML(event.time || "Time not listed")}</time><span class="admin-agenda-event-color" aria-hidden="true"></span>
            <div class="admin-agenda-event-info"><strong>${escapeHTML(event.title || "Facility calendar event")}</strong><small>${escapeHTML(event.instrument || "Unassigned instrument")} · ${event.source === "portal" ? "Website booking" : "Brown Bear · managed externally"}</small></div>
            ${event.source === "portal" && event.bookingId ? `<div class="admin-agenda-actions"><button class="admin-detail-button" type="button" data-booking-edit="${escapeHTML(event.bookingId)}">Edit</button><button class="admin-delete-button" type="button" data-booking-delete="${escapeHTML(event.bookingId)}">Delete</button></div>` : '<span class="admin-external-badge">External</span>'}
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

  async function loadDashboard() {
    const [bookingResult, calendarResult, instrumentsResult] = await Promise.allSettled([
      loadBookings(),
      loadFacilityCalendar(),
      fetchJSON(`${apiBase}/instruments`, { cache: "no-store" }),
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
  }

  async function checkSession() {
    try {
      const payload = await fetchJSON(`${apiBase}/admin/session`, { cache: "no-store" });
      showDashboard(payload.authenticated);
      if (payload.authenticated) await loadDashboard();
    } catch (error) {
      loginStatus.textContent = error.message;
    }
  }

  loginForm.addEventListener("submit", async event => {
    event.preventDefault();
    loginStatus.textContent = "";
    const submitButton = loginForm.querySelector('[type="submit"]');
    submitButton.disabled = true;
    try {
      await fetchJSON(`${apiBase}/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: loginForm.elements.password.value }),
      });
      loginForm.reset();
      showDashboard(true);
      await loadDashboard();
    } catch (error) {
      loginStatus.textContent = error.message;
    } finally {
      submitButton.disabled = false;
    }
  });

  adminPortal.querySelector("#admin-logout").addEventListener("click", async () => {
    try {
      await fetchJSON(`${apiBase}/admin/logout`, { method: "POST" });
      bookings = [];
      showDashboard(false);
      loginStatus.textContent = "You have been signed out.";
    } catch (error) {
      dashboardStatus.textContent = error.message;
    }
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
    if (!booking || !window.confirm(`Permanently delete booking ${booking.id} and its uploaded user form? This cannot be undone.`)) return;
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

  function openEditDialog(booking) {
    editingBookingId = booking.id;
    document.querySelector("#admin-edit-title").textContent = `Change sessions · ${booking.id}`;
    editStatus.textContent = "";
    const instrumentOptions = instruments.map(instrument =>
      `<option value="${escapeHTML(instrument.name)}">${escapeHTML(instrument.name)}</option>`
    ).join("");
    editSlots.innerHTML = booking.slots.map((slot, index) => `
      <fieldset class="admin-edit-slot" data-edit-slot>
        <legend>Session ${index + 1}</legend>
        <label>Instrument<select name="instrument" required>${instrumentOptions}</select></label>
        <label>Date<input name="date" type="date" min="${facilityDateOffset()}" max="${facilityDateOffset(90)}" required value="${escapeHTML(slot.date)}"></label>
        <label>Time<select name="time" required>${bookingTimes.map(time =>
          `<option value="${time}">${formatTimeSlot(time)}</option>`
        ).join("")}</select></label>
      </fieldset>`).join("");
    [...editSlots.querySelectorAll("[data-edit-slot]")].forEach((row, index) => {
      row.querySelector('[name="instrument"]').value = booking.slots[index].instrument;
      row.querySelector('[name="time"]').value = booking.slots[index].time;
      const dateInput = row.querySelector('[name="date"]');
      dateInput.addEventListener("change", () => {
        const weekday = new Date(`${dateInput.value}T12:00:00`).getDay();
        dateInput.setCustomValidity(weekday === 0 || weekday === 6
          ? "Choose a weekday; weekend sessions are not available."
          : "");
      });
    });
    editDialog.showModal();
  }

  editForm.addEventListener("submit", async event => {
    event.preventDefault();
    if (!editingBookingId || !editForm.reportValidity()) return;
    const slots = [...editSlots.querySelectorAll("[data-edit-slot]")].map(row => ({
      instrument: row.querySelector('[name="instrument"]').value,
      date: row.querySelector('[name="date"]').value,
      time: row.querySelector('[name="time"]').value,
    }));
    const submitButton = editForm.querySelector('[type="submit"]');
    submitButton.disabled = true;
    editStatus.textContent = "Checking live conflicts and saving…";
    try {
      const payload = await fetchJSON(`${apiBase}/admin/bookings/${encodeURIComponent(editingBookingId)}/slots`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slots }),
      });
      bookings = bookings.map(booking => booking.id === editingBookingId ? payload.booking : booking);
      editDialog.close();
      renderStats();
      renderBookings();
      await loadFacilityCalendar();
      dashboardStatus.textContent = `Booking ${editingBookingId} sessions updated.`;
    } catch (error) {
      editStatus.textContent = error.message;
    } finally {
      submitButton.disabled = false;
    }
  });

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
    if (deleteButton) void deleteBooking(deleteButton.dataset.bookingDelete, deleteButton);
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
        </dl><a class="btn primary admin-detail-download" href="${apiBase}/admin/bookings/${encodeURIComponent(booking.id)}/form" target="_blank" rel="noreferrer">Download ${escapeHTML(booking.formName)}</a>`;
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
      dashboardStatus.textContent = `Booking ${bookingId} updated.`;
    } catch (error) {
      dashboardStatus.textContent = error.message;
      statusButton.disabled = false;
    }
  });

  document.querySelector("[data-close-admin-detail]").addEventListener("click", () => detailDialog.close());
  detailDialog.addEventListener("click", event => {
    if (event.target === detailDialog) detailDialog.close();
  });

  const now = new Date();
  calendarMonthInput.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  void checkSession();
}
