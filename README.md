# Flow Cytometry Facility — IISc website

## Open the preview

For the live, in-page Brown Bear schedule, start the Flask app with
`run_backend.bat`, then open `http://127.0.0.1:5000/`. The Flask app serves the
website and calendar API from the same local address.

You can also open `preview.html` or `frontend/index.html` directly for a static
preview; the live schedule requires the backend to be running.

## Website features

- Responsive layout inspired by the supplied IISc facility reference
- Persistent dark navigation rail with a compact mobile menu
- Simple research-focused homepage with direct links to detailed pages
- Separate About, People, Instruments, Data Analysis, Forms & Resources,
  booking portal, staff admin portal, Workshops and Contact pages
- Instrument cards with analyzer/sorter filters
- Mobile navigation with active-page and instrument-filter highlighting
- Team portraits stored with the People page assets
- Individual supplied image tiles for the homepage, each page header, and the
  IISc seal and campus image in the sidebar
- Homepage monthly overview chart with day-by-day Brown Bear calendar and portal
  booking counts, daily details, month navigation and live refresh
- Live Brown Bear instrument category colors are mapped to the facility's
  instrument palette in the homepage overview
- Multi-instrument booking form with live slot availability, booking details,
  required completed user-form upload, pending staff review and slot conflict checks
- Password-protected booking dashboard with an interactive weekday month grid,
  selected-day agenda and instrument filter; staff can review, accept, decline,
  create, edit and delete website bookings, with secure form downloads
- Supabase PostgreSQL and private Storage deployment path for durable hosted
  bookings, session conflict constraints, form files and audit history
- Hover and focus elevation on cards and links
- Clickable map link for directions to the Division of Biological Sciences
- Facility committee, staff, offline-analysis software, research links,
  facility documents and workshop archive

The facility calendar combines live Brown Bear sessions with pending and
confirmed website bookings. A submitted request blocks its selected slots while
it awaits staff review; accepting it confirms the booking and emails the user.
New requests generate an acknowledgement to the user and a notification to the
configured facility administrator. The booking portal checks Brown Bear event
times as well as portal reservations, and overlapping slots are marked
unavailable and rejected by the booking API. Availability refreshes every 30
seconds while the booking page is visible, on return to the page, and
immediately before submission. Pending and confirmed portal bookings appear on
the website calendar and homepage overview. Brown
Bear remains managed separately: this site has no write access to that external
calendar, so website bookings are not written back to Brown Bear.
Sessions run hourly from 10:00 AM to 1:00 PM and 2:00 PM to 5:00 PM. Consecutive
sorter sessions can be booked together; the next contiguous session after the
last booked sorter session is blocked for cleaning. No more than two instruments
can be booked for the same time slot across Brown Bear and portal bookings.
The staff portal labels Brown Bear events as externally managed and links to
Brown Bear's separate admin sign-in. Authorized staff can edit or delete those
legacy events there; website bookings can be rescheduled or deleted in this
portal, with live conflict checks against both sources.

Facility content is organized in `frontend/data/site-content.json` and
`frontend/data/instruments.json`. The posted user-charge PDF is dated 2023, and
the listed 2024 workshop has passed; contact the facility to confirm current
information.

## Local API

The Flask API exposes:

- `GET /api/health`
- `GET /api/instruments`
- `GET /api/content`
- `GET /api/calendar?month=YYYY-MM` (Brown Bear schedule plus pending/confirmed portal sessions)
- `GET /api/booking-availability?start=YYYY-MM-DD&end=YYYY-MM-DD`
- `POST /api/bookings` (multipart booking details and completed PDF form)
- `POST /api/admin/login`, `POST /api/admin/logout`
- `GET /api/admin/bookings`, `GET /api/admin/calendar?month=YYYY-MM`
- `POST /api/admin/bookings` (create a confirmed staff booking)
- `PUT /api/admin/bookings/<id>` (edit booking details and sessions)
- `PATCH /api/admin/bookings/<id>` (change booking status)
- `PUT /api/admin/bookings/<id>/slots` (reschedule sessions)
- `DELETE /api/admin/bookings/<id>`
- `GET /api/admin/bookings/<id>/form` (admin-only download)

To run the API:

```bash
cd backend
pip install -r requirements.txt
set BOOKING_ADMIN_PASSWORD=your-unique-admin-password
set FLASK_SECRET_KEY=your-long-random-session-secret
python app.py
```

Open `http://127.0.0.1:5000/booking.html` to book a session and
`http://127.0.0.1:5000/admin.html` to manage bookings. Set `BOOKING_ADMIN_PASSWORD`
on the server before using the admin portal. For a deployed HTTPS site, set
`BOOKING_COOKIE_SECURE=true` and persist both the Flask `instance` directory
(booking database and uploaded forms) and the session secret across restarts.
Configure `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM_EMAIL`
to send mail; configure `ADMIN_NOTIFICATION_EMAIL` for new-request alerts.
Optional settings are `SMTP_PORT` (defaults to 587) and `SMTP_USE_SSL`.
Without working mail configuration, bookings are still saved, but the API and
portal report that delivery failed instead of claiming that mail was sent.
For Supabase-backed hosting, follow [SUPABASE_SETUP.md](./SUPABASE_SETUP.md);
the server uses Supabase PostgreSQL and a private Storage bucket when
`DATABASE_URL` is configured, and retains SQLite for local development.
