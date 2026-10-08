# Supabase and production hosting

The Flask server remains the only application API. It stores booking records in
Supabase PostgreSQL and completed PDF forms in a **private** Supabase Storage
bucket. The browser never connects to Supabase directly and must never receive
the database URL or service-role key.

## 1. Create the production project

1. Create a Supabase project in the region closest to the facility (choose the
   nearest supported India region if available).
2. Keep a separate Supabase project for development and production.
3. Open **SQL Editor** in the production project and run every SQL file in
   [`supabase/migrations`](./supabase/migrations/) in filename order. In
   particular, `20261001090000_booking_approval_workflow.sql` must be applied:
   the initial schema migration only allows `confirmed` and `cancelled`, while
   new booking requests are saved with status `pending`. Omitting the approval
   migration makes submissions fail when the database rejects that status.
4. Confirm the migrations create `bookings`, `booking_sessions`,
   `booking_audit_log`, `calendar_closures`, `facility_events`,
   `facility_workshop_archive`, `instruments`, and the private
   `booking-forms` and `workshop-images` buckets. The tables have RLS enabled
   and no `anon`/`authenticated` table grants. Only the backend's trusted
   database connection and Storage service role should access booking
   information, forms, and workshop photos.

The schema keeps the current booking API compatible while maintaining a
normalized session table. PostgreSQL enforces that confirmed sessions for the
same instrument cannot overlap, including when two requests race. Status,
reschedule, and deletion changes are recorded in an audit table without copying
the user's contact details into the audit log. The four instrument records are
seeded from the current site palette.

## 2. Configure the hosted Flask service

Deploy this repository to a Python web host that supports a persistent Flask
web service. The root [`Procfile`](./Procfile) starts Gunicorn with two workers.
Install dependencies from `backend/requirements.txt` and configure these as
**server-side environment variables** in the host's secret/environment settings:

| Variable | Value |
| --- | --- |
| `APP_ENV` | `production` (prevents an accidental fallback to ephemeral SQLite if `DATABASE_URL` is missing). |
| `DATABASE_URL` | Supabase PostgreSQL transaction-pooler connection string with SSL. Use the connection string from the project's Database settings and URL-encode special characters in the password. |
| `SUPABASE_URL` | Project URL, such as `https://<project-ref>.supabase.co`. |
| `SUPABASE_SERVICE_ROLE_KEY` | A server-only service-role key from the project's API settings. Never use it in HTML, JavaScript, or a public variable. |
| `SUPABASE_STORAGE_BUCKET` | `booking-forms` (change the SQL migration too if you intentionally rename it). |
| `FLASK_SECRET_KEY` | A long random secret that remains unchanged across deployments and restarts. |
| `BOOKING_ADMIN_PASSWORD` | A unique, strong admin password stored only in the host's secret settings. |
| `BOOKING_COOKIE_SECURE` | `true` for the hosted HTTPS site. |
| `SMTP_HOST` | SMTP provider hostname for booking notifications. |
| `SMTP_PORT` | SMTP port; defaults to `587` for STARTTLS. |
| `SMTP_USE_SSL` | `false` for STARTTLS on port `587`; set `true` for implicit TLS (usually port `465`). |
| `SMTP_USERNAME` | SMTP account username. |
| `SMTP_PASSWORD` | SMTP account password or provider-issued app password. |
| `SMTP_FROM_EMAIL` | Verified sender address accepted by the SMTP provider. |
| `ADMIN_NOTIFICATION_EMAIL` | Facility address that receives new booking requests. |

Use [`.env.mail.example`](./.env.mail.example) as a list of mail variable names
and placeholder values. Enter the real values directly in Render's Environment
settings; the example file is not loaded automatically and contains no secrets.
Verify mail delivery with the SMTP provider's test tools and a test booking.

The Supabase URL, service-role key, database URL, Flask key, and admin password
must not be committed to the repository. Use [`.env.mail.example`](./.env.mail.example)
for mail variable names only; do not copy its placeholders into production.

### Render deployment check

In the Render web service's **Environment** settings, add the server-side
variables from the table above using the actual values from the production
Supabase project. In particular, `DATABASE_URL` alone is not enough: when it is
set, the app requires both `SUPABASE_URL` and
`SUPABASE_SERVICE_ROLE_KEY` for Supabase-backed persistence, followed by a
persistent `FLASK_SECRET_KEY`. Save the settings and redeploy the service.

Run all SQL migrations in that same Supabase project, in filename order, before
using bookings. If a submission reports "The booking could not be saved," check
the service logs for a database constraint error and confirm that
`20261001090000_booking_approval_workflow.sql` has been applied; it enables the
`pending` status required for new booking requests. After the deployment is
live, `https://<your-service>.onrender.com/api/health`
should return HTTP 200 with status `ok` and persistence `supabase`, and
`/api/calendar?month=YYYY-MM` should return HTTP 200. Brown Bear entries remain
available from that calendar endpoint if persistence is temporarily
misconfigured; its `portalBookingsAvailable` field will be `false` and the
website will indicate that portal bookings are missing. The health check,
booking availability and booking submissions still require working Supabase
configuration. Website bookings are not written back to Brown Bear.

The existing admin login uses one server-configured password. For a public
production deployment, restrict staff access at the hosting layer or plan a
follow-up migration to individual Supabase Auth accounts with MFA and roles.
Do not expose the admin portal as a public data API.

## 3. Move existing local bookings (optional)

Apply the SQL migration first, then run the importer from a trusted machine that
has access to the existing SQLite database and PDF folder. Set `DATABASE_URL`,
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `FLASK_SECRET_KEY` in that
machine's environment.
For example, in PowerShell:

```powershell
uv run --with-requirements backend\requirements.txt -- python backend\migrate_sqlite_to_supabase.py
```

By default, the importer reads `backend\instance\bookings.sqlite3` and
`backend\instance\booking-forms`. Override those locations with `--source-db`
and `--source-uploads` if needed. It preserves booking IDs and timestamps,
uploads PDFs to the private bucket, and skips IDs already present so it can be
re-run after an interrupted transfer. Keep the original SQLite database and
uploads unchanged until the imported counts and sample PDF downloads have been
verified in production.

## 4. Long-term data and backup plan

- **Retention:** No automatic cleanup is enabled. Booking records contain
  personal and potentially sensitive research information; agree a retention
  period with facility and institute policy owners before deleting or archiving
  old records. Deleting a booking removes its form from the live bucket, while
  the audit table retains a minimal change record.
- **Backups:** Enable the database backup/PITR options available on the chosen
  Supabase plan. Separately export encrypted copies of Storage PDFs to an
  institute-controlled backup destination; do not assume a database backup
  includes the file contents. Test restoring both tables and PDFs periodically.
- **Operations:** Keep development and production projects separate, monitor
  database/storage usage and failed API requests, and rotate service credentials
  if exposed. Use migrations for schema changes; do not hand-edit production
  tables.
- **Static site content:** Page text, images, and the public instrument catalog
  remain version-controlled site assets. They are configuration/content rather
  than user-generated records and are deployed with the site. Supabase stores
  booking submissions, session rows, audit history, and uploaded PDFs. Brown
  Bear's calendar remains externally managed and is fetched live rather than
  copied into this database.

## Local preview

Without `DATABASE_URL`, the app continues to use its local SQLite database and
local upload directory. This keeps the preview and tests self-contained. A
configured Supabase connection requires the backend secrets above and uses the
PostgreSQL/Storage services instead.
