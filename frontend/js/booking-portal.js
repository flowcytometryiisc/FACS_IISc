const bookingPortal = document.querySelector("[data-booking-portal]");

if (bookingPortal) {
  const apiBase = "/api";
  const instrumentList = bookingPortal.querySelector("#booking-instruments");
  const dateList = bookingPortal.querySelector("#booking-dates");
  const slotList = bookingPortal.querySelector("#booking-slots");
  const dateHeading = bookingPortal.querySelector("#booking-slot-date");
  const availabilityStatus = bookingPortal.querySelector("#booking-availability-status");
  const refreshAvailabilityButton = bookingPortal.querySelector("[data-booking-refresh]");
  const selectedList = bookingPortal.querySelector("#booking-selected-list");
  const selectedCount = bookingPortal.querySelector("#booking-selected-count");
  const selectionSummary = bookingPortal.querySelector("#booking-selection-summary");
  const submitStatus = bookingPortal.querySelector("#booking-submit-status");
  const form = bookingPortal.querySelector("#booking-form");
  const confirmation = document.querySelector("#booking-confirmation");
  const today = new Date();
  const dates = [];
  const instruments = [];
  const timeSlots = ["10:00-11:00", "11:00-12:00", "12:00-13:00", "14:00-15:00", "15:00-16:00", "16:00-17:00"];
  const sorterCleaningNext = new Map(timeSlots.flatMap((time, index) => {
    const next = timeSlots[index + 1];
    return next && time.split("-")[1] === next.split("-")[0] ? [[time, next]] : [];
  }));
  const selectedInstruments = new Set();
  const selectedSlots = new Map();
  const holidaysByDate = new Map();
  let holidayCalendarYears = new Set();
  let selectedDate = "";
  let bookedSlots = new Map();
  let unavailableSlots = new Map();
  let availabilityError = "";
  let availabilityLoaded = false;
  let availabilityRefreshing = false;
  let availabilityRefreshPromise = null;
  let availabilityUpdatedAt = null;
  const availabilityRefreshInterval = 30 * 1000;

  function localDateKey(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }

  function slotKey(slot) {
    return `${slot.instrument}|${slot.date}|${slot.time}`;
  }

  function formatDate(value, options) {
    return new Intl.DateTimeFormat("en-IN", options).format(new Date(`${value}T12:00:00`));
  }

  function formatTimeSlot(value) {
    return value.split("-").map(part => {
      const [hourText, minute] = part.split(":");
      const hour = Number(hourText);
      return `${hour % 12 || 12}:${minute} ${hour < 12 ? "AM" : "PM"}`;
    }).join(" – ");
  }

  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    })[character]);
  }

  async function fetchJSON(url, options = {}) {
    const response = await fetch(url, options);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The booking service could not complete your request.");
    return payload;
  }

  function renderInstruments() {
    instrumentList.innerHTML = instruments.map((instrument, index) => {
      const active = selectedInstruments.has(instrument.name);
      const color = instrument.color || "gray";
      const safeName = instrument.name.replace(/[&<>"']/g, character => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      })[character]);
      return `<button class="booking-instrument${active ? " selected" : ""}" data-instrument-color="${color}" type="button" data-instrument-index="${index}" aria-pressed="${active}">
        <span class="booking-instrument-check" aria-hidden="true">${active ? "✓" : ""}</span><span><strong>${safeName}</strong><small>${instrument.type} · ${instrument.manufacturer}</small></span>
      </button>`;
    }).join("");
  }

  function renderDates() {
    dateList.innerHTML = dates.map(value => {
      const selected = value === selectedDate;
      const holiday = holidaysByDate.get(value);
      const unsupportedYear = !holidayCalendarYears.has(value.slice(0, 4));
      const dateNote = holiday?.name || (unsupportedYear ? "Holiday list pending" : formatDate(value, { month: "short" }));
      return `<button type="button" class="booking-date${selected ? " selected" : ""}${holiday || unsupportedYear ? " holiday" : ""}" title="${escapeHTML(dateNote)}" data-booking-date="${value}" aria-pressed="${selected}">
        <span>${formatDate(value, { weekday: "short" })}</span><strong>${formatDate(value, { day: "numeric" })}</strong><small>${escapeHTML(dateNote)}</small>
      </button>`;
    }).join("");
    dateList.querySelectorAll("[data-booking-date]").forEach(button => {
      button.addEventListener("click", () => {
        selectedDate = button.dataset.bookingDate;
        renderDates();
        renderSlots();
      });
    });
  }

  function renderSlots() {
    const selectedHoliday = holidaysByDate.get(selectedDate);
    const selectedYearUnavailable = selectedDate && !holidayCalendarYears.has(selectedDate.slice(0, 4));
    dateHeading.textContent = selectedDate
      ? `${formatDate(selectedDate, { weekday: "long", day: "numeric", month: "long" })}${selectedHoliday
        ? ` · IISc Holiday: ${selectedHoliday.name}`
        : selectedYearUnavailable ? " · IISc holiday list pending" : ""}`
      : "Select a date";
    const chosen = instruments.filter(instrument => selectedInstruments.has(instrument.name));
    if (!chosen.length) {
      slotList.innerHTML = '<p class="booking-inline-status">Choose at least one instrument to see its time slots.</p>';
      return;
    }
    if (availabilityError) {
      slotList.innerHTML = `<p class="booking-error">${availabilityError === "Refreshing availability…" ? availabilityError : `Availability could not be confirmed: ${availabilityError}`}</p>`;
      return;
    }
    if (!availabilityLoaded) {
      slotList.innerHTML = '<p class="booking-inline-status">Checking live facility calendar availability…</p>';
      return;
    }

    slotList.innerHTML = chosen.map(instrument => {
      const name = instrument.name.replace(/[&<>"']/g, character => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      })[character]);
      const timeOptions = timeSlots.map(time => {
        const slot = { instrument: instrument.name, date: selectedDate, time };
        const key = slotKey(slot);
        const selected = selectedSlots.has(key);
        const existingBooking = bookedSlots.get(key);
        const booked = Boolean(existingBooking && existingBooking.source !== "cleaning");
        const unavailableReason = unavailableSlots.get(`${selectedDate}|${time}`);
        const selectedCleaning = instrument.type === "Sorter"
          && [...selectedSlots.values()].some(item =>
            item.instrument === instrument.name
            && item.date === selectedDate
            && sorterCleaningNext.get(item.time) === time
          );
        const operatorBookings = new Set([
          ...[...bookedSlots.values()]
            .filter(item => item.date === selectedDate && item.time === time && item.source !== "cleaning")
            .map(item => item.instrument),
          ...[...selectedSlots.values()]
            .filter(item => item.date === selectedDate && item.time === time)
            .map(item => item.instrument),
        ]);
        const operatorLimit = !selected && !operatorBookings.has(instrument.name)
          && (operatorBookings.size >= 2 || unavailableReason?.reason === "operator_limit");
        const cleaning = existingBooking?.source === "cleaning";
        const selectableCleaning = selectedCleaning && !cleaning && !selected;
        const unavailable = Boolean(unavailableReason) || operatorLimit;
        const status = cleaning
          ? "Blocked for cleaning"
          : unavailableReason?.type === "exception"
            ? `Exception holiday · ${unavailableReason.remark}`
            : unavailableReason?.type === "workshop"
              ? `Workshop holiday · ${unavailableReason.remark}`
          : booked
            ? existingBooking.source === "calendar"
              ? "Booked · Facility calendar"
              : `Booked · ${existingBooking.userName}${existingBooking.status === "pending" ? " · Under review" : ""}`
            : selected
              ? "Selected"
              : selectableCleaning
                ? "Continue sorter booking"
              : operatorLimit
                ? "Operator limit reached"
                : unavailableReason?.reason === "holiday"
                  ? `IISc Holiday · ${holidaysByDate.get(selectedDate)?.name || "Closed"}`
                  : unavailableReason?.reason === "holiday_calendar_unavailable"
                    ? "IISc holiday list pending"
                : unavailableReason?.reason === "started"
                  ? "Session started"
                  : unavailableReason?.reason === "weekend"
                    ? "Not bookable"
                    : unavailable ? "Unavailable" : "Available";
        const disabled = booked || cleaning || unavailable || availabilityRefreshing;
        const button = `<button type="button" class="booking-time-slot${selected ? " selected" : ""}${booked ? " booked" : ""}${cleaning ? " cleaning" : ""}${unavailable ? " unavailable" : ""}" data-slot-key="${key}" ${disabled ? "disabled" : ""} aria-pressed="${selected}"><span>${formatTimeSlot(time)}</span><small>${escapeHTML(availabilityRefreshing && !booked && !cleaning && !unavailable ? "Checking…" : status)}</small></button>`;
        return button;
      }).join("");
      return `<section class="booking-instrument-slots" data-instrument-color="${instrument.color || "gray"}"><h4>${name} · ${instrument.type}</h4><div class="booking-time-grid">${timeOptions}</div></section>`;
    }).join("");
    slotList.querySelectorAll("[data-slot-key]").forEach(button => {
      button.addEventListener("click", () => {
        if (availabilityRefreshing) return;
        const key = button.dataset.slotKey;
        if (selectedSlots.has(key)) {
          selectedSlots.delete(key);
        } else if (selectedSlots.size >= 12) {
          availabilityStatus.textContent = "You can select up to 12 sessions per booking.";
          return;
        } else {
          const [instrument, date, time] = key.split("|");
          const concurrent = new Set([
            ...[...bookedSlots.values()]
              .filter(item => item.date === date && item.time === time && item.source !== "cleaning")
              .map(item => item.instrument),
            ...[...selectedSlots.values()]
              .filter(item => item.date === date && item.time === time)
              .map(item => item.instrument),
          ]);
          if (concurrent.size >= 2 && !concurrent.has(instrument)) {
            availabilityStatus.textContent = "Only two instruments can be booked during the same time slot.";
            return;
          }
          selectedSlots.set(key, { instrument, date, time });
        }
        availabilityStatus.textContent = "";
        renderSlots();
        renderSelectedSlots();
      });
    });
  }

  function renderSelectedSlots() {
    const slots = [...selectedSlots.values()];
    selectedCount.textContent = slots.length
      ? `${slots.length} ${slots.length === 1 ? "session" : "sessions"} selected`
      : "No sessions selected";
    if (!slots.length) {
      selectedList.innerHTML = "<p>Select available slots to add them here.</p>";
      selectionSummary.textContent = "Select one or more available sessions above.";
      return;
    }
    selectedList.innerHTML = slots.map(slot => {
      const name = slot.instrument.replace(/[&<>"']/g, character => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      })[character]);
      const instrument = instruments.find(item => item.name === slot.instrument);
      return `<div class="booking-selected-item" data-instrument-color="${instrument?.color || "gray"}"><span><strong>${name}</strong><small>${formatDate(slot.date, { weekday: "short", day: "numeric", month: "short" })} · ${formatTimeSlot(slot.time)}</small></span><button type="button" data-remove-slot="${slotKey(slot)}" aria-label="Remove ${name} session">×</button></div>`;
    }).join("");
    selectionSummary.textContent = `${slots.length} session${slots.length === 1 ? "" : "s"} selected · Slots will be held while staff review your request.`;
    selectedList.querySelectorAll("[data-remove-slot]").forEach(button => {
      button.addEventListener("click", () => {
        selectedSlots.delete(button.dataset.removeSlot);
        renderSlots();
        renderSelectedSlots();
      });
    });
  }

  function loadAvailability() {
    if (availabilityRefreshPromise) return availabilityRefreshPromise;
    const start = dates[0];
    const end = dates[dates.length - 1];
    if (!start || !end) return Promise.reject(new Error("No bookable weekdays are available in the booking window."));
    availabilityRefreshing = true;
    availabilityError = "";
    refreshAvailabilityButton.disabled = true;
    availabilityStatus.textContent = "Checking live facility calendar and website bookings…";
    renderSlots();
    availabilityRefreshPromise = (async () => {
      try {
      const payload = await fetchJSON(`${apiBase}/booking-availability?start=${start}&end=${end}`, { cache: "no-store" });
      bookedSlots = new Map(payload.booked.map(slot => [slotKey(slot), slot]));
      unavailableSlots = new Map(payload.unavailable.map(slot => [`${slot.date}|${slot.time}`, slot]));
      holidaysByDate.clear();
      payload.holidays.forEach(holiday => holidaysByDate.set(holiday.date, holiday));
      holidayCalendarYears = new Set(payload.holidayCalendarYears);
      let selectionChanged = false;
      for (const key of selectedSlots.keys()) {
        if (bookedSlots.has(key) || unavailableSlots.has(`${selectedSlots.get(key).date}|${selectedSlots.get(key).time}`)) {
          selectedSlots.delete(key);
          selectionChanged = true;
        }
      }
      availabilityError = "";
      availabilityLoaded = true;
      availabilityUpdatedAt = Date.now();
      renderDates();
      if (selectionChanged) {
        renderSelectedSlots();
        availabilityStatus.textContent = "Availability refreshed. A selected session is no longer available and was removed.";
      } else {
        const updatedAt = new Intl.DateTimeFormat("en-IN", {
          hour: "numeric",
          minute: "2-digit",
          second: "2-digit",
        }).format(availabilityUpdatedAt);
        availabilityStatus.textContent = `Availability synced with the facility calendar at ${updatedAt}.`;
      }
      return selectionChanged;
      } catch (error) {
        availabilityError = error.message;
        availabilityStatus.textContent = error.message;
        throw error;
      } finally {
        availabilityRefreshing = false;
        refreshAvailabilityButton.disabled = false;
        renderSlots();
      }
    })();
    return availabilityRefreshPromise.finally(() => {
      availabilityRefreshPromise = null;
    });
  }

  instrumentList.addEventListener("click", event => {
    const button = event.target.closest("[data-instrument-index]");
    if (!button) return;
    const instrument = instruments[Number(button.dataset.instrumentIndex)];
    if (selectedInstruments.has(instrument.name)) {
      selectedInstruments.delete(instrument.name);
      for (const [key, slot] of selectedSlots) {
        if (slot.instrument === instrument.name) selectedSlots.delete(key);
      }
    } else {
      selectedInstruments.add(instrument.name);
    }
    renderInstruments();
    renderSlots();
    renderSelectedSlots();
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();
    submitStatus.textContent = "";
    if (!selectedSlots.size) {
      submitStatus.textContent = "Choose at least one available session before confirming.";
      return;
    }
    if (!form.reportValidity()) return;
    const upload = form.elements.userForm.files[0];
    if (!upload || upload.size > 10 * 1024 * 1024 || !upload.name.toLowerCase().endsWith(".pdf")) {
      submitStatus.textContent = "Attach a PDF facility user form smaller than 10 MB.";
      return;
    }
    const selectedBeforeRefresh = [...selectedSlots.keys()];
    const submitButton = form.querySelector('[type="submit"]');
    submitButton.disabled = true;
    submitButton.setAttribute("aria-busy", "true");
    submitStatus.textContent = "Submitting your request for staff review…";
    try {
      await loadAvailability();
      if (selectedBeforeRefresh.some(key => !selectedSlots.has(key))) {
        submitStatus.textContent = "One or more selected sessions are no longer available. Review the updated selection and try again.";
        return;
      }
      const payload = new FormData(form);
      payload.set("slots", JSON.stringify([...selectedSlots.values()]));
      const booking = await fetchJSON(`${apiBase}/bookings`, { method: "POST", body: payload });
      document.querySelector("#booking-confirmation-id").textContent = booking.id;
      document.querySelector("#booking-confirmation-slots").textContent =
        `${booking.slots.length} session${booking.slots.length === 1 ? "" : "s"} held while staff review your request`;
      document.querySelector("#booking-confirmation-email").textContent =
        booking.notifications?.user?.sent
          ? "We sent an email acknowledging your request."
          : `Your request is saved, but the acknowledgement email was not sent: ${booking.notifications?.user?.error || "delivery status unavailable"}`;
      confirmation.showModal();
      selectedSlots.clear();
      form.reset();
      renderSelectedSlots();
      await loadAvailability();
      submitStatus.textContent = "";
    } catch (error) {
      submitStatus.textContent = error.message;
      if (error.message.includes("Refresh availability") || error.message.includes("facility calendar")) {
        try { await loadAvailability(); } catch (availabilityError) {
          availabilityStatus.textContent = availabilityError.message;
        }
      }
    } finally {
      submitButton.disabled = false;
      submitButton.removeAttribute("aria-busy");
    }
  });

  document.querySelector("[data-close-booking-confirmation]").addEventListener("click", () => confirmation.close());
  confirmation.addEventListener("click", event => {
    if (event.target === confirmation) confirmation.close();
  });

  async function initializeBookingPortal() {
    try {
      const response = await fetchJSON(`${apiBase}/instruments`);
      instruments.push(...response);
      if (instruments.length) selectedInstruments.add(instruments[0].name);
      const query = new URLSearchParams(window.location.search);
      const requestedDate = query.get("date");
      const requestedInstrument = query.get("instrument");
      if (instruments.some(instrument => instrument.name === requestedInstrument)) {
        selectedInstruments.clear();
        selectedInstruments.add(requestedInstrument);
      }
      let firstDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());
      const lastBookableDate = new Date(today.getFullYear(), today.getMonth() + 2, 0);
      if (requestedDate && /^\d{4}-\d{2}-\d{2}$/.test(requestedDate)) {
        const [year, month, day] = requestedDate.split("-").map(Number);
        const parsed = new Date(year, month - 1, day);
        const withinBookingWindow = parsed >= firstDate
          && parsed <= lastBookableDate
          && localDateKey(parsed) === requestedDate;
        if (withinBookingWindow) firstDate = parsed;
      }
      while (firstDate <= lastBookableDate && firstDate.getDay() === 0) {
        firstDate.setDate(firstDate.getDate() + 1);
      }
      if (firstDate > lastBookableDate) {
        firstDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());
        while (firstDate.getDay() === 0) firstDate.setDate(firstDate.getDate() + 1);
      }
      for (let day = new Date(firstDate); day <= lastBookableDate; day.setDate(day.getDate() + 1)) {
        if (day.getDay() !== 0) dates.push(localDateKey(day));
      }
      selectedDate = dates[0];
      renderInstruments();
      renderDates();
      renderSlots();
      renderSelectedSlots();
    } catch (error) {
      instrumentList.innerHTML = `<p class="booking-error">${error.message}</p>`;
      slotList.innerHTML = '<p class="booking-error">Instrument options could not be loaded.</p>';
      return;
    }
    try {
      await loadAvailability();
    } catch {
      slotList.innerHTML = `<p class="booking-error">Availability could not be confirmed: ${availabilityError}</p>`;
    }
  }

  refreshAvailabilityButton.addEventListener("click", () => {
    void loadAvailability().catch(error => {
      availabilityStatus.textContent = error.message;
    });
  });

  window.setInterval(() => {
    if (!dates.length || document.visibilityState !== "visible" || confirmation.open) return;
    void loadAvailability().catch(error => {
      availabilityStatus.textContent = `Live availability refresh failed: ${error.message}`;
    });
  }, availabilityRefreshInterval);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible" || !availabilityLoaded || confirmation.open) return;
    if (Date.now() - availabilityUpdatedAt < availabilityRefreshInterval) return;
    void loadAvailability().catch(error => {
      availabilityStatus.textContent = `Live availability refresh failed: ${error.message}`;
    });
  });

  void initializeBookingPortal();
}
