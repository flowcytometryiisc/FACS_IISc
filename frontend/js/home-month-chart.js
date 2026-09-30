const homeMonthOverview = document.querySelector("[data-home-month-overview]");

if (homeMonthOverview) {
  const apiBase = window.location.protocol === "file:" ? "http://127.0.0.1:5000/api" : "/api";
  const monthLabel = homeMonthOverview.querySelector("#home-month-label");
  const daysContainer = homeMonthOverview.querySelector("#home-month-days");
  const metricsContainer = homeMonthOverview.querySelector("#home-month-metrics");
  const selectedDateLabel = homeMonthOverview.querySelector("#home-month-selected-date");
  const eventsContainer = homeMonthOverview.querySelector("#home-month-events");
  const statusLabel = homeMonthOverview.querySelector("#home-month-status");
  const refreshButton = homeMonthOverview.querySelector("[data-home-month-refresh]");
  const today = new Date();
  let visibleMonth = new Date(today.getFullYear(), today.getMonth(), 1);
  let selectedDate = localDateKey(weekdayInMonth(new Date(today)));
  let brownBearEvents = [];
  let portalSlots = [];
  let instruments = [];
  let monthStatus = { brownBear: "loading", portal: "loading" };
  let requestToken = 0;

  function localDateKey(value) {
    return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
  }

  function formatDate(value, options) {
    return new Intl.DateTimeFormat("en-IN", options).format(new Date(`${value}T12:00:00`));
  }

  function monthKey() {
    return `${visibleMonth.getFullYear()}-${String(visibleMonth.getMonth() + 1).padStart(2, "0")}`;
  }

  function weekdayDayNumbers(year, month) {
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    return Array.from({ length: daysInMonth }, (_unused, index) => index + 1)
      .filter(day => {
        const weekday = new Date(year, month, day).getDay();
        return weekday !== 0 && weekday !== 6;
      });
  }

  function weekdayInMonth(date) {
    const originalYear = date.getFullYear();
    const originalMonth = date.getMonth();
    const weekday = date.getDay();
    if (weekday === 6) date.setDate(date.getDate() + 2);
    else if (weekday === 0) date.setDate(date.getDate() + 1);
    if (date.getMonth() !== originalMonth || date.getFullYear() !== originalYear) {
      date = new Date(originalYear, originalMonth + 1, 0);
      while (date.getDay() === 0 || date.getDay() === 6) date.setDate(date.getDate() - 1);
    }
    return date;
  }

  async function fetchJSON(url) {
    const response = await fetch(url, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The facility schedule could not be loaded.");
    return payload;
  }

  function eventsForDate(date) {
    return [
      ...brownBearEvents.filter(event => event.date === date).map(event => ({
        source: event.instrument ? `Brown Bear · ${event.instrument}` : "Brown Bear · Unassigned",
        time: event.time || "Time not listed",
        title: event.title,
        color: event.color || "neutral",
      })),
      ...portalSlots.filter(slot => slot.date === date).map(slot => ({
        source: "Portal booking",
        time: slot.time.replace("-", " – "),
        title: slot.instrument,
        color: slot.color || instruments.find(instrument => instrument.name === slot.instrument)?.color || "gray",
      })),
    ];
  }

  function renderMetrics() {
    const year = visibleMonth.getFullYear();
    const month = visibleMonth.getMonth();
    const weekdayDays = weekdayDayNumbers(year, month);
    const dayCounts = weekdayDays.map(day =>
      eventsForDate(`${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`).length
    );
    const total = dayCounts.reduce((sum, count) => sum + count, 0);
    const busyDays = dayCounts.filter(count => count > 0).length;
    const busiest = Math.max(0, ...dayCounts);
    const metrics = [
      ["Schedule entries", monthStatus.brownBear === "loaded" || monthStatus.portal === "loaded" ? total : "—"],
      ["Days with activity", monthStatus.brownBear === "loaded" || monthStatus.portal === "loaded" ? `${busyDays} / ${weekdayDays.length}` : "—"],
      ["Busiest day", monthStatus.brownBear === "loaded" || monthStatus.portal === "loaded"
        ? busiest ? `${busiest} entries` : "No entries yet"
        : "—"],
    ];
    metricsContainer.innerHTML = metrics.map(([label, value]) =>
      `<article class="home-month-metric"><span>${label}</span><strong>${value}</strong></article>`
    ).join("");
  }

  function renderDayDetail() {
    selectedDateLabel.textContent = formatDate(selectedDate, {
      weekday: "long", day: "numeric", month: "long", year: "numeric",
    });
    const events = eventsForDate(selectedDate);
    if (!events.length) {
      eventsContainer.innerHTML = '<p class="home-month-empty">No sessions are listed for this day.</p>';
      return;
    }
    eventsContainer.innerHTML = events.map(event => `
      <article class="home-month-event">
        <span class="home-month-event-time">${escapeHTML(event.time)}</span>
        <span class="home-month-event-mark" data-instrument-color="${escapeHTML(event.color)}" aria-hidden="true"></span>
        <span><strong>${escapeHTML(event.title)}</strong><small>${escapeHTML(event.source)}</small></span>
      </article>`).join("");
  }

  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }

  function renderDays() {
    const year = visibleMonth.getFullYear();
    const month = visibleMonth.getMonth();
    const weekdayDays = weekdayDayNumbers(year, month);
    const firstDay = new Date(year, month, 1).getDay();
    const leadingDays = firstDay === 0 || firstDay === 6 ? 0 : firstDay - 1;
    const counts = weekdayDays.map(day => {
      const value = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      return {
        day,
        date: value,
        live: brownBearEvents.filter(event => event.date === value).length,
        byColor: [
          ...instruments.map(instrument => ({
            color: instrument.color,
            count: brownBearEvents.filter(event => event.date === value && event.instrument === instrument.name).length
              + portalSlots.filter(slot => slot.date === value && slot.instrument === instrument.name).length,
          })),
          { color: "neutral", count: brownBearEvents.filter(event => event.date === value && !event.instrument).length },
        ].filter(item => item.count > 0),
        portal: portalSlots.filter(slot => slot.date === value).length,
      };
    });
    const maximum = Math.max(1, ...counts.map(item => item.live + item.portal));
    monthLabel.textContent = formatDate(localDateKey(visibleMonth), { month: "long", year: "numeric" });

    const cells = Array.from({ length: leadingDays }, () =>
      '<span class="home-month-day-spacer" aria-hidden="true"></span>'
    );
    cells.push(...counts.map(item => {
      const day = item.day;
      const total = item.live + item.portal;
      const selected = selectedDate === item.date;
      const isToday = localDateKey(today) === item.date;
      const title = `${formatDate(item.date, { weekday: "long", day: "numeric", month: "long" })}: ${item.live} Brown Bear calendar entries, ${item.portal} portal bookings`;
      const bars = item.byColor.map(group =>
        `<i data-instrument-color="${escapeHTML(group.color)}" style="height:${Math.max(9, Math.round(group.count / maximum * 46))}px"></i>`
      ).join("");
      return `<button type="button" class="home-month-day${selected ? " selected" : ""}${isToday ? " today" : ""}" data-home-month-date="${item.date}" aria-pressed="${selected}" aria-label="${escapeHTML(title)}">
        <span class="home-month-day-number">${day}</span><span class="home-month-bars" aria-hidden="true">${bars}</span><span class="home-month-count">${total ? `${total} ${total === 1 ? "entry" : "entries"}` : "—"}</span>
      </button>`;
    }));
    const trailingDays = (5 - (cells.length % 5)) % 5;
    cells.push(...Array.from({ length: trailingDays }, () =>
      '<span class="home-month-day-spacer" aria-hidden="true"></span>'
    ));
    daysContainer.innerHTML = cells.join("");
    daysContainer.querySelectorAll("[data-home-month-date]").forEach(button => {
      button.addEventListener("click", () => {
        selectedDate = button.dataset.homeMonthDate;
        renderDays();
        renderDayDetail();
      });
    });
    renderMetrics();
    renderDayDetail();
  }

  function renderStatus() {
    const parts = [];
    if (monthStatus.brownBear === "loaded") parts.push(`${brownBearEvents.length} Brown Bear entries`);
    else if (monthStatus.brownBear === "error") parts.push("Brown Bear calendar could not be reached");
    if (monthStatus.portal === "loaded") parts.push(`${portalSlots.length} portal sessions`);
    else if (monthStatus.portal === "error") parts.push("Portal bookings could not be loaded");
    statusLabel.textContent = parts.join(" · ") || "Loading both live schedule sources…";
    refreshButton.disabled = monthStatus.brownBear === "loading" || monthStatus.portal === "loading";
    renderLegend();
  }

  function renderLegend() {
    const legend = homeMonthOverview.querySelector(".home-month-legend");
    const colors = instruments.map(instrument =>
      `<span><i data-instrument-color="${escapeHTML(instrument.color)}"></i>${escapeHTML(instrument.name)}<small>${escapeHTML(instrument.colorCode || "")}</small></span>`
    );
    legend.innerHTML = `<span><i data-instrument-color="neutral"></i>Unassigned</span>${colors.join("")}`;
  }

  async function loadMonth() {
    const currentToken = ++requestToken;
    const month = monthKey();
    const [yearValue, monthValue] = month.split("-").map(Number);
    const start = `${month}-01`;
    const end = localDateKey(new Date(yearValue, monthValue, 0));
    brownBearEvents = [];
    portalSlots = [];
    monthStatus = { brownBear: "loading", portal: "loading" };
    renderDays();
    renderStatus();

    const results = await Promise.allSettled([
      fetchJSON(`${apiBase}/calendar?month=${encodeURIComponent(month)}`),
      fetchJSON(`${apiBase}/booking-availability?start=${start}&end=${end}`),
      fetchJSON(`${apiBase}/instruments`),
    ]);
    if (currentToken !== requestToken) return;

    const calendarResult = results[0];
    const portalResult = results[1];
    if (calendarResult.status === "fulfilled" && calendarResult.value.month === month
      && Array.isArray(calendarResult.value.events)) {
      brownBearEvents = calendarResult.value.events.filter(event => event.source !== "portal");
      monthStatus.brownBear = "loaded";
    } else {
      monthStatus.brownBear = "error";
      console.error("Unable to sync the Brown Bear monthly calendar.",
        calendarResult.status === "rejected" ? calendarResult.reason : "The calendar returned an unexpected response.");
    }
    if (portalResult.status === "fulfilled" && Array.isArray(portalResult.value.booked)) {
      portalSlots = portalResult.value.booked.filter(slot => slot.source === "portal");
      monthStatus.portal = "loaded";
    } else {
      monthStatus.portal = "error";
      console.error("Unable to load portal booking data.",
        portalResult.status === "rejected" ? portalResult.reason : "The portal returned an unexpected response.");
    }
    const instrumentResult = results[2];
    if (instrumentResult.status === "fulfilled" && Array.isArray(instrumentResult.value)) {
      instruments = instrumentResult.value;
    } else {
      console.error("Unable to load the instrument color palette.",
        instrumentResult.status === "rejected" ? instrumentResult.reason : "The instrument catalog returned an unexpected response.");
    }
    renderDays();
    renderStatus();
  }

  homeMonthOverview.querySelectorAll("[data-home-month-step]").forEach(button => {
    button.addEventListener("click", () => {
      visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + Number(button.dataset.homeMonthStep), 1);
      const todayMonth = new Date(today.getFullYear(), today.getMonth(), 1);
      selectedDate = localDateKey(visibleMonth.getTime() === todayMonth.getTime()
        ? weekdayInMonth(new Date(today))
        : weekdayInMonth(new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1)));
      void loadMonth();
    });
  });

  homeMonthOverview.querySelector("[data-home-month-today]").addEventListener("click", () => {
    visibleMonth = new Date(today.getFullYear(), today.getMonth(), 1);
    selectedDate = localDateKey(weekdayInMonth(new Date(today)));
    void loadMonth();
  });

  refreshButton.addEventListener("click", () => { void loadMonth(); });
  void loadMonth();
}
