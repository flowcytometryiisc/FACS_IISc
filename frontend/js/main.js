const instruments = [
  {
    name: "CytoFLEX LX",
    color: "purple",
    manufacturer: "Beckman Coulter",
    type: "Analyzer",
    description: "Flow cytometer analyzer. Operator-assisted.",
    image: "assets/images/instruments/cytoflex-lx.jpg",
    specifications: ["Manufacturer: Beckman Coulter", "Category: Analyzer", "Function: Flow cytometry analysis", "Operation: Operator-assisted"]
  },
  {
    name: "Discover S8 Spectral Flow Cytometer",
    color: "teal",
    manufacturer: "BD",
    type: "Sorter",
    description: "Spectral flow cytometer. Operator-assisted.",
    image: "assets/images/instruments/discover-s8.jpg",
    specifications: ["Manufacturer: BD", "Category: Cell sorter", "Function: Spectral flow cytometry", "Operation: Operator-assisted"]
  },
  {
    name: "Symphony A1",
    color: "blue",
    manufacturer: "BD",
    type: "Analyzer",
    description: "Flow cytometer analyzer. Operator-assisted.",
    image: "assets/images/instruments/symphony-a1.jpg",
    specifications: ["Manufacturer: BD", "Category: Analyzer", "Function: Flow cytometry analysis", "Operation: Operator-assisted"]
  },
  {
    name: "FACSAria™ Fusion",
    color: "gray",
    manufacturer: "BD",
    type: "Sorter",
    description: "Cell sorter with advanced features. Operator-assisted.",
    image: "assets/images/instruments/facsaria-fusion.jpg",
    specifications: ["Manufacturer: BD", "Category: Cell sorter", "Function: Cell sorting", "Operation: Operator-assisted"]
  }
];

function escapeHTML(value) {
  return value.replace(/[&<>"']/g, character => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[character]);
}

function instrumentSlug(name) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

const grid = document.querySelector("#instrument-grid");
const filters = [...document.querySelectorAll(".filter[data-filter]")];

function renderInstruments(filter = "all") {
  if (!grid) return;
  const items = filter === "all" ? instruments : instruments.filter(instrument => instrument.type === filter);
  const previewLimit = Number(grid.dataset.limit);
  const visibleItems = previewLimit ? items.slice(0, previewLimit) : items;
  grid.innerHTML = visibleItems.map(instrument => {
    const name = escapeHTML(instrument.name);
    const manufacturer = escapeHTML(instrument.manufacturer);
    const type = escapeHTML(instrument.type);
    const description = escapeHTML(instrument.description);
    const image = escapeHTML(instrument.image);
    return `
      <article class="instrument-card" data-instrument-color="${instrument.color}" id="${instrumentSlug(instrument.name)}" aria-label="${name}, ${type}" role="button" tabindex="0" aria-haspopup="dialog" aria-controls="instrument-details">
        <div class="instrument-art"><img src="${image}" alt="${name}" loading="lazy" decoding="async"></div>
        <div class="instrument-info">
          <h3>${name}</h3>
          <p>${manufacturer}</p>
          <span class="type ${instrument.type === "Sorter" ? "sorter" : ""}" title="${description}">${type}</span>
        </div>
      </article>`;
  }).join("");
}

renderInstruments();

if (grid) {
  const instrumentDialog = document.createElement("dialog");
  instrumentDialog.id = "instrument-details";
  instrumentDialog.className = "instrument-dialog";
  instrumentDialog.setAttribute("aria-labelledby", "instrument-dialog-title");
  instrumentDialog.innerHTML = `
    <div class="instrument-dialog-header">
      <span class="eyebrow">INSTRUMENT DETAILS</span>
      <button class="instrument-dialog-close" type="button" aria-label="Close instrument details">&times;</button>
    </div>
    <div class="instrument-dialog-layout">
      <div class="instrument-dialog-image"><img alt="" decoding="async"></div>
      <div class="instrument-dialog-copy">
        <h2 id="instrument-dialog-title"></h2>
        <p class="instrument-dialog-manufacturer"></p>
        <h3>Specifications</h3>
        <ul class="instrument-dialog-specifications"></ul>
        <a class="btn primary instrument-dialog-book" href="booking.html">Book this instrument <b>→</b></a>
      </div>
    </div>`;
  document.body.append(instrumentDialog);

  const dialogImage = instrumentDialog.querySelector(".instrument-dialog-image img");
  const dialogTitle = instrumentDialog.querySelector("#instrument-dialog-title");
  const dialogManufacturer = instrumentDialog.querySelector(".instrument-dialog-manufacturer");
  const dialogSpecifications = instrumentDialog.querySelector(".instrument-dialog-specifications");
  const dialogBookLink = instrumentDialog.querySelector(".instrument-dialog-book");

  function openInstrumentDialog(card) {
    const instrument = instruments.find(item => instrumentSlug(item.name) === card.id);
    if (!instrument) return;
    dialogTitle.textContent = instrument.name;
    dialogImage.src = instrument.image;
    dialogImage.alt = instrument.name;
    dialogManufacturer.textContent = instrument.manufacturer;
    dialogSpecifications.innerHTML = instrument.specifications
      .map(specification => `<li>${escapeHTML(specification)}</li>`)
      .join("");
    dialogBookLink.href = `booking.html?instrument=${encodeURIComponent(instrument.name)}`;
    instrumentDialog.showModal();
  }

  grid.addEventListener("click", event => {
    const card = event.target.closest(".instrument-card");
    if (card && grid.contains(card)) openInstrumentDialog(card);
  });

  grid.addEventListener("keydown", event => {
    const card = event.target.closest(".instrument-card");
    if (!card || !grid.contains(card) || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    openInstrumentDialog(card);
  });

  instrumentDialog.querySelector(".instrument-dialog-close").addEventListener("click", () => {
    instrumentDialog.close();
  });

  instrumentDialog.addEventListener("click", event => {
    if (event.target === instrumentDialog) instrumentDialog.close();
  });
}

filters.forEach(button => {
  button.addEventListener("click", () => {
    filters.forEach(filterButton => {
      const active = filterButton === button;
      filterButton.classList.toggle("active", active);
      filterButton.setAttribute("aria-pressed", String(active));
    });
    renderInstruments(button.dataset.filter);
  });
});

const hashFilter = filters.find(button => button.id && `#${button.id}` === window.location.hash);
hashFilter?.click();

const calendarBrowser = document.querySelector("[data-calendar-browser]");

if (calendarBrowser) {
  const calendarApiUrl = calendarBrowser.dataset.calendarApi || (
    window.location.protocol === "file:"
      ? "http://127.0.0.1:5000/api/calendar"
      : "/api/calendar"
  );
  const monthLabel = calendarBrowser.querySelector("#calendar-month");
  const dateInput = calendarBrowser.querySelector("#calendar-date");
  const dateGrid = calendarBrowser.querySelector("#calendar-dates");
  const selectedDateLabel = calendarBrowser.querySelector("#calendar-selected-date");
  const bookDateLink = calendarBrowser.querySelector("#calendar-book-date");
  const bookSessionLink = calendarBrowser.querySelector("#calendar-book-session");
  const scheduleTitle = calendarBrowser.querySelector("#calendar-schedule-title");
  const scheduleStatus = calendarBrowser.querySelector("#calendar-live-status");
  const eventsContainer = calendarBrowser.querySelector("#calendar-events");
  const refreshButton = calendarBrowser.querySelector("[data-calendar-refresh]");
  const instrumentLegend = calendarBrowser.querySelector(".calendar-instrument-legend");
  const today = new Date();
  let selectedDate = weekdayInMonth(new Date(today.getFullYear(), today.getMonth(), today.getDate()));
  let visibleMonth = new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1);
  let loadedMonth = "";
  let pendingMonth = "";
  let scheduleEvents = [];
  let scheduleError = "";
  let lastUpdated = "";
  let requestId = 0;

  function formatCalendarDate(date, options) {
    return new Intl.DateTimeFormat("en-IN", options).format(date);
  }

  function dateKey(date) {
    return [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0")
    ].join("-");
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

  function renderSchedule() {
    instrumentLegend.innerHTML = instruments.map(instrument =>
      `<span><i data-instrument-color="${instrument.color}"></i>${escapeHTML(instrument.name)}</span>`
    ).join("") + '<span><i data-instrument-color="neutral"></i>Other / holiday</span>';
    const selectedDateString = dateKey(selectedDate);
    scheduleTitle.textContent = `Schedule for ${formatCalendarDate(selectedDate, {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric"
    })}`;

    if (scheduleError) {
      scheduleStatus.textContent = scheduleError;
      eventsContainer.innerHTML = '<div class="calendar-empty">Try refreshing later, or contact the facility team to confirm the schedule.</div>';
      return;
    }

    if (loadedMonth !== `${selectedDate.getFullYear()}-${String(selectedDate.getMonth() + 1).padStart(2, "0")}`) {
      scheduleStatus.textContent = "Loading bookings from Brown Bear…";
      eventsContainer.innerHTML = '<div class="calendar-empty">Syncing the selected month…</div>';
      return;
    }

    const dayEvents = scheduleEvents.filter(event => event.date === selectedDateString);
    const updated = lastUpdated
      ? ` · Updated ${new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit" }).format(new Date(lastUpdated))}`
      : "";
    const bookingAvailabilityNotice = calendarBrowser.dataset.portalBookingsAvailable === "false"
      ? " · Website bookings temporarily unavailable"
      : "";
    scheduleStatus.textContent = `${dayEvents.length} ${dayEvents.length === 1 ? "booking" : "bookings"} listed · India Standard Time${updated}${bookingAvailabilityNotice}`;

    if (!dayEvents.length) {
      eventsContainer.innerHTML = '<div class="calendar-empty">No sessions are listed for this day in the facility calendar.</div>';
      return;
    }

    eventsContainer.innerHTML = dayEvents.map(event => `
      <article class="calendar-event" data-instrument-color="${escapeHTML(event.color || "neutral")}">
        <span class="calendar-event-time">${escapeHTML(event.time || "All day")}</span>
        <span class="calendar-event-mark" aria-hidden="true"></span>
        <span class="calendar-event-copy"><strong>${escapeHTML(event.title)}</strong>${event.instrument ? `<small>${event.source === "portal" ? "Portal booking · " : ""}${escapeHTML(event.instrument)}</small>` : ""}</span>
      </article>`).join("");
  }

  async function loadMonth(forceRefresh = false) {
    const monthKey = `${selectedDate.getFullYear()}-${String(selectedDate.getMonth() + 1).padStart(2, "0")}`;
    if (!forceRefresh && loadedMonth === monthKey) {
      renderSchedule();
      return;
    }
    if (!forceRefresh && pendingMonth === monthKey) return;

    const currentRequestId = ++requestId;
    pendingMonth = monthKey;
    scheduleError = "";
    scheduleStatus.textContent = "Loading bookings from Brown Bear…";
    eventsContainer.innerHTML = '<div class="calendar-empty">Syncing the selected month…</div>';
    refreshButton.disabled = true;
    refreshButton.setAttribute("aria-busy", "true");

    try {
      const response = await fetch(`${calendarApiUrl}?month=${encodeURIComponent(monthKey)}`, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "The Brown Bear calendar could not be loaded.");
      }
      if (payload.month !== monthKey || !Array.isArray(payload.events) || !payload.events.every(event =>
        event && typeof event.date === "string" && typeof event.title === "string" && typeof event.time === "string"
        && typeof event.color === "string" && typeof event.instrument === "string"
      )) {
        throw new Error("The Brown Bear calendar returned data in an unexpected format.");
      }
      if (currentRequestId !== requestId) return;

      loadedMonth = monthKey;
      scheduleEvents = payload.events;
      lastUpdated = payload.fetchedAt || "";
      scheduleError = "";
      calendarBrowser.dataset.portalBookingsAvailable = String(payload.portalBookingsAvailable !== false);
      updateCalendarDateIndicators();
      renderSchedule();
    } catch (error) {
      if (currentRequestId !== requestId) return;
      loadedMonth = "";
      scheduleEvents = [];
      scheduleError = "The live schedule could not be synced from Brown Bear.";
      renderSchedule();
      console.error("Unable to sync the Brown Bear facility calendar.", error);
    } finally {
      if (currentRequestId === requestId) {
        pendingMonth = "";
        refreshButton.disabled = false;
        refreshButton.removeAttribute("aria-busy");
      }
    }
  }

  function updateCalendarDateIndicators() {
    dateGrid.querySelectorAll("[data-calendar-date]").forEach(button => {
      const dayEvents = scheduleEvents.filter(event => event.date === button.dataset.calendarDate);
      const colors = [...new Set(dayEvents.map(event => event.color || "neutral"))];
      const instrumentsBooked = [...new Set(dayEvents.map(event => event.instrument).filter(Boolean))];
      const detail = dayEvents.length
        ? ` · ${dayEvents.length} ${dayEvents.length === 1 ? "booking" : "bookings"}${instrumentsBooked.length ? ` · ${instrumentsBooked.join(", ")}` : ""}`
        : "";
      button.setAttribute("aria-label", `${formatCalendarDate(new Date(`${button.dataset.calendarDate}T12:00:00`), {
        weekday: "long",
        day: "numeric",
        month: "long",
        year: "numeric"
      })}${detail}`);
      const dayNumber = Number(button.dataset.calendarDate.slice(-2));
      const marks = colors.length
        ? `<span class="calendar-date-colors" aria-hidden="true">${colors.map(color =>
          `<i data-instrument-color="${escapeHTML(color)}"></i>`
        ).join("")}</span>`
        : "";
      button.innerHTML = `${dayNumber}${marks}`;
    });
  }

  function updateCalendar() {
    const year = visibleMonth.getFullYear();
    const month = visibleMonth.getMonth();
    const firstDay = new Date(year, month, 1);
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const firstWeekday = firstDay.getDay();
    const leadingDays = firstWeekday === 0 || firstWeekday === 6 ? 0 : firstWeekday - 1;
    const selectedDateString = dateKey(selectedDate);
    monthLabel.textContent = formatCalendarDate(visibleMonth, { month: "long", year: "numeric" });
    dateInput.value = selectedDateString;
    selectedDateLabel.textContent = formatCalendarDate(selectedDate, {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric"
    });
    const bookingUrl = `booking.html?date=${encodeURIComponent(selectedDateString)}`;
    bookDateLink.href = bookingUrl;
    bookSessionLink.href = bookingUrl;
    const buttons = Array.from({ length: leadingDays }, () =>
      '<span class="calendar-date-spacer" aria-hidden="true"></span>'
    );
    for (let dayNumber = 1; dayNumber <= daysInMonth; dayNumber += 1) {
      const date = new Date(year, month, dayNumber);
      if (date.getDay() === 0 || date.getDay() === 6) continue;
      const dateString = [
        date.getFullYear(),
        String(date.getMonth() + 1).padStart(2, "0"),
        String(date.getDate()).padStart(2, "0")
      ].join("-");
      const selected = dateString === selectedDateString;
      const isToday = dateString === [
        today.getFullYear(),
        String(today.getMonth() + 1).padStart(2, "0"),
        String(today.getDate()).padStart(2, "0")
      ].join("-");
      const classes = [
        "calendar-date",
        selected ? "selected" : "",
        isToday ? "today" : ""
      ].filter(Boolean).join(" ");

      buttons.push(`<button class="${classes}" type="button" data-calendar-date="${dateString}" aria-label="${formatCalendarDate(date, {
        weekday: "long",
        day: "numeric",
        month: "long",
        year: "numeric"
      })}" aria-pressed="${selected}">${date.getDate()}</button>`);
    }
    const trailingDays = (5 - (buttons.length % 5)) % 5;
    buttons.push(...Array.from({ length: trailingDays }, () =>
      '<span class="calendar-date-spacer" aria-hidden="true"></span>'
    ));

    dateGrid.innerHTML = buttons.join("");
    updateCalendarDateIndicators();
    dateGrid.querySelectorAll("[data-calendar-date]").forEach(button => {
      button.addEventListener("click", () => {
        const [yearValue, monthValue, dayValue] = button.dataset.calendarDate.split("-").map(Number);
        selectedDate = new Date(yearValue, monthValue - 1, dayValue);
        visibleMonth = new Date(yearValue, monthValue - 1, 1);
        updateCalendar();
      });
    });
    renderSchedule();
    void loadMonth();
  }

  calendarBrowser.querySelectorAll("[data-calendar-month-step]").forEach(button => {
    button.addEventListener("click", () => {
      const targetMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth() + Number(button.dataset.calendarMonthStep), 1);
      const targetDay = Math.min(selectedDate.getDate(), new Date(targetMonth.getFullYear(), targetMonth.getMonth() + 1, 0).getDate());
      visibleMonth = targetMonth;
      selectedDate = weekdayInMonth(new Date(targetMonth.getFullYear(), targetMonth.getMonth(), targetDay));
      updateCalendar();
    });
  });

  calendarBrowser.querySelector("[data-calendar-today]").addEventListener("click", () => {
    selectedDate = weekdayInMonth(new Date(today.getFullYear(), today.getMonth(), today.getDate()));
    visibleMonth = new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1);
    updateCalendar();
  });

  dateInput.addEventListener("change", () => {
    if (!dateInput.value) return;
    const [year, month, day] = dateInput.value.split("-").map(Number);
    selectedDate = weekdayInMonth(new Date(year, month - 1, day));
    visibleMonth = new Date(year, month - 1, 1);
    updateCalendar();
  });

  refreshButton.addEventListener("click", () => {
    void loadMonth(true);
  });

  updateCalendar();
}

const navigation = document.querySelector("#site-navigation");
const menuToggle = document.querySelector(".menu-toggle");

function closeNavigation() {
  if (!navigation || !menuToggle) return;
  navigation.classList.remove("open");
  menuToggle.setAttribute("aria-expanded", "false");
}

if (navigation && menuToggle) {
  menuToggle.addEventListener("click", () => {
    const isOpen = menuToggle.getAttribute("aria-expanded") === "true";
    menuToggle.setAttribute("aria-expanded", String(!isOpen));
    navigation.classList.toggle("open", !isOpen);
  });
  navigation.querySelectorAll("a").forEach(link => link.addEventListener("click", closeNavigation));
  document.addEventListener("click", event => {
    if (!navigation.contains(event.target) && !menuToggle.contains(event.target)) closeNavigation();
  });
}
