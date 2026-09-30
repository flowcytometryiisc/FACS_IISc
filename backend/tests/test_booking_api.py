import io
import json
import os
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as facility_app
import migrate_sqlite_to_supabase as booking_migration


class BookingApiTests(unittest.TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory()
        storage_path = Path(self.storage.name)
        self.database_patch = patch.object(
            facility_app, "BOOKING_DATABASE", storage_path / "bookings.sqlite3"
        )
        self.uploads_patch = patch.object(
            facility_app, "BOOKING_UPLOADS", storage_path / "booking-forms"
        )
        self.database_patch.start()
        self.uploads_patch.start()
        self.calendar_response_patch = patch.object(
            facility_app,
            "urlopen",
            return_value=self.calendar_response(
                b'<table class="CalBlock"><tr class="DayHeaderRow"><td class="DayHeader">'
                b'<a href="?Date=2026-09-30">30</a></td></tr><tr class="DayRow"><td></td></tr></table>'
            ),
        )
        self.calendar_response_patch.start()
        self.password_patch = patch.dict(os.environ, {"BOOKING_ADMIN_PASSWORD": "test-admin-password"})
        self.password_patch.start()
        facility_app.app.config.update(TESTING=True)
        self.client = facility_app.app.test_client()
        slot_date = facility_app.facility_today() + timedelta(days=1)
        while slot_date.weekday() >= 5:
            slot_date += timedelta(days=1)
        self.slot = {
            "instrument": facility_app.load_json("instruments.json")[0]["name"],
            "date": slot_date.isoformat(),
            "time": "09:00-11:00",
        }

    def tearDown(self):
        self.password_patch.stop()
        self.uploads_patch.stop()
        self.database_patch.stop()
        self.calendar_response_patch.stop()
        self.storage.cleanup()

    @staticmethod
    def calendar_response(html):
        response = MagicMock()
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = html
        response.__enter__.return_value = response
        response.__exit__.return_value = None
        return response

    def booking_data(self, slot=None):
        return {
            "userName": "Alex Researcher",
            "piName": "Dr. Example",
            "phone": "+91 98765 43210",
            "email": "alex@example.edu",
            "department": "Biological Sciences",
            "specimen": "Cell suspension",
            "notes": "Panel setup and analysis",
            "slots": json.dumps([slot or self.slot]),
            "userForm": (io.BytesIO(b"%PDF-1.4\nTest form"), "facility-form.pdf"),
        }

    def sign_in(self):
        return self.client.post(
            "/api/admin/login",
            json={"password": "test-admin-password"},
        )

    def test_booking_reserves_slot_and_admin_can_cancel_and_restore(self):
        created = self.client.post("/api/bookings", data=self.booking_data())
        self.assertEqual(created.status_code, 201)
        booking = created.get_json()
        self.assertEqual(booking["status"], "confirmed")

        availability = self.client.get(
            f"/api/booking-availability?start={self.slot['date']}&end={self.slot['date']}"
        )
        booked_slot = availability.get_json()["booked"][0]
        self.assertEqual(
            {key: booked_slot[key] for key in ("instrument", "date", "time")},
            self.slot,
        )
        self.assertEqual(booked_slot["color"], "purple")
        self.assertEqual(booked_slot["source"], "portal")
        calendar = self.client.get(
            f"/api/calendar?month={self.slot['date'][:7]}"
        ).get_json()
        portal_events = [
            event for event in calendar["events"] if event["source"] == "portal"
        ]
        self.assertEqual(len(portal_events), 1)
        self.assertEqual(portal_events[0]["title"], "Portal booking")
        self.assertNotIn("Alex Researcher", json.dumps(portal_events))
        conflict = self.client.post("/api/bookings", data=self.booking_data())
        self.assertEqual(conflict.status_code, 409)

        self.assertEqual(self.client.get("/api/admin/bookings").status_code, 401)
        self.assertEqual(self.sign_in().status_code, 200)
        listing = self.client.get("/api/admin/bookings")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.get_json()["bookings"][0]["userName"], "Alex Researcher")
        self.assertEqual(listing.get_json()["bookings"][0]["slots"][0]["color"], "purple")

        download = self.client.get(f"/api/admin/bookings/{booking['id']}/form")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, b"%PDF-1.4\nTest form")
        download.close()

        cancelled = self.client.patch(
            f"/api/admin/bookings/{booking['id']}", json={"status": "cancelled"}
        )
        self.assertEqual(cancelled.get_json()["booking"]["status"], "cancelled")
        self.assertEqual(
            self.client.get(
                f"/api/booking-availability?start={self.slot['date']}&end={self.slot['date']}"
            ).get_json()["booked"],
            [],
        )
        replacement = self.client.post("/api/bookings", data=self.booking_data())
        self.assertEqual(replacement.status_code, 201)
        conflict = self.client.patch(
            f"/api/admin/bookings/{booking['id']}", json={"status": "confirmed"}
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.client.get("/api/admin/bookings").status_code, 200)
        self.assertEqual(self.client.post("/api/admin/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/admin/bookings").status_code, 401)
        self.sign_in()
        self.client.patch(
            f"/api/admin/bookings/{replacement.get_json()['id']}",
            json={"status": "cancelled"},
        )
        restored = self.client.patch(
            f"/api/admin/bookings/{booking['id']}", json={"status": "confirmed"}
        )
        self.assertEqual(restored.get_json()["booking"]["status"], "confirmed")

    def test_booking_rejects_invalid_user_form_and_invalid_slot(self):
        invalid_file = self.booking_data()
        invalid_file["userForm"] = (io.BytesIO(b"not a PDF"), "facility-form.pdf")
        self.assertEqual(self.client.post("/api/bookings", data=invalid_file).status_code, 400)

        invalid_slot = self.booking_data({
            **self.slot,
            "time": "00:00-01:00",
        })
        self.assertEqual(self.client.post("/api/bookings", data=invalid_slot).status_code, 400)

    def test_booking_rejects_a_slot_that_has_already_started(self):
        current = facility_app.facility_now()
        if current.hour < 9:
            self.skipTest("No facility session has started yet today.")
        started_time = next(
            time for time in reversed(facility_app.BOOKING_SLOTS)
            if time.split("-", 1)[0] <= current.strftime("%H:%M")
        )
        today_slot = {
            **self.slot,
            "date": current.date().isoformat(),
            "time": started_time,
        }
        response = self.client.post("/api/bookings", data=self.booking_data(today_slot))
        self.assertEqual(response.status_code, 400)

        availability = self.client.get(
            f"/api/booking-availability?start={today_slot['date']}&end={today_slot['date']}"
        )
        self.assertIn(
            {"date": today_slot["date"], "time": started_time},
            availability.get_json()["unavailable"],
        )

    def test_live_calendar_bookings_block_overlapping_instrument_slots(self):
        event = {
            "date": self.slot["date"],
            "time": "09:30 AM - 10:30 AM",
            "title": "Existing CytoFLEX session",
            "instrument": self.slot["instrument"],
            "color": "purple",
        }
        with patch.object(
            facility_app, "fetch_brown_bear_month", return_value=[event]
        ):
            availability = self.client.get(
                f"/api/booking-availability?start={self.slot['date']}&end={self.slot['date']}"
            )
            self.assertEqual(availability.status_code, 200)
            booked = availability.get_json()["booked"]
            self.assertIn(
                {
                    "instrument": self.slot["instrument"],
                    "date": self.slot["date"],
                    "time": "09:00-11:00",
                    "color": "purple",
                    "source": "calendar",
                    "title": "Existing CytoFLEX session",
                },
                booked,
            )
            self.assertNotIn(
                "11:00-13:00",
                [slot["time"] for slot in booked if slot["instrument"] == self.slot["instrument"]],
            )
            other_instrument = next(
                item["name"] for item in facility_app.load_json("instruments.json")
                if item["name"] != self.slot["instrument"]
            )
            self.assertNotIn(
                (other_instrument, "09:00-11:00"),
                [(slot["instrument"], slot["time"]) for slot in booked],
            )
            longer_event_slots = facility_app.brown_bear_booked_slots(
                [{
                    **event,
                    "time": "10:00 AM - 1:00 PM",
                }],
                facility_app.load_json("instruments.json"),
            )
            self.assertEqual(
                [slot["time"] for slot in longer_event_slots
                 if slot["instrument"] == self.slot["instrument"]],
                ["09:00-11:00", "11:00-13:00"],
            )
            conflict = self.client.post(
                "/api/bookings", data=self.booking_data()
            )
        self.assertEqual(conflict.status_code, 409)
        self.assertIn("facility calendar", conflict.get_json()["error"])

    def test_booking_rechecks_brown_bear_after_availability_was_loaded(self):
        event = {
            "date": self.slot["date"],
            "time": "09:30 AM - 10:30 AM",
            "title": "Just-added Brown Bear session",
            "instrument": self.slot["instrument"],
            "color": "purple",
        }
        with patch.object(
            facility_app,
            "fetch_brown_bear_month",
            side_effect=[[], [event]],
        ) as fetch_calendar:
            availability = self.client.get(
                f"/api/booking-availability?start={self.slot['date']}&end={self.slot['date']}"
            )
            self.assertEqual(availability.status_code, 200)
            self.assertEqual(availability.get_json()["booked"], [])

            booking = self.client.post(
                "/api/bookings", data=self.booking_data()
            )

        self.assertEqual(fetch_calendar.call_count, 2)
        self.assertEqual(booking.status_code, 409)
        self.assertIn("facility calendar", booking.get_json()["error"])

    def test_admin_can_reschedule_booking_and_calendar_shows_portal_and_brown_bear(self):
        created = self.client.post("/api/bookings", data=self.booking_data())
        booking_id = created.get_json()["id"]
        self.assertEqual(self.sign_in().status_code, 200)

        calendar = self.client.get(
            f"/api/admin/calendar?month={self.slot['date'][:7]}"
        )
        self.assertEqual(calendar.status_code, 200)
        self.assertEqual(calendar.headers["Cache-Control"], "no-store")
        portal_events = [
            event for event in calendar.get_json()["events"]
            if event["source"] == "portal"
        ]
        self.assertEqual(len(portal_events), 1)
        self.assertEqual(portal_events[0]["bookingId"], booking_id)

        replacement_date = facility_app.facility_today() + timedelta(days=2)
        while replacement_date.weekday() >= 5:
            replacement_date += timedelta(days=1)
        replacement_slot = {
            **self.slot,
            "date": replacement_date.isoformat(),
            "time": "11:00-13:00",
        }
        updated = self.client.put(
            f"/api/admin/bookings/{booking_id}/slots",
            json={"slots": [replacement_slot]},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["booking"]["slots"][0]["date"], replacement_slot["date"])
        original_availability = self.client.get(
            f"/api/booking-availability?start={self.slot['date']}&end={self.slot['date']}"
        ).get_json()
        self.assertFalse(any(slot.get("source") == "portal" for slot in original_availability["booked"]))
        replacement_availability = self.client.get(
            f"/api/booking-availability?start={replacement_slot['date']}&end={replacement_slot['date']}"
        ).get_json()
        self.assertTrue(any(slot.get("source") == "portal" for slot in replacement_availability["booked"]))

    def test_admin_reschedule_rejects_brown_bear_conflict(self):
        created = self.client.post("/api/bookings", data=self.booking_data())
        booking_id = created.get_json()["id"]
        self.sign_in()
        event = {
            "date": self.slot["date"],
            "time": "09:30 AM - 10:30 AM",
            "title": "Brown Bear session",
            "instrument": self.slot["instrument"],
            "color": "purple",
        }
        with patch.object(facility_app, "fetch_brown_bear_month", return_value=[event]):
            updated = self.client.put(
                f"/api/admin/bookings/{booking_id}/slots",
                json={"slots": [self.slot]},
            )
        self.assertEqual(updated.status_code, 409)
        self.assertIn("Brown Bear", updated.get_json()["error"])

    def test_admin_can_delete_booking_and_remove_its_uploaded_form(self):
        created = self.client.post("/api/bookings", data=self.booking_data())
        booking_id = created.get_json()["id"]
        connection = facility_app.booking_connection()
        try:
            row = connection.execute(
                "SELECT form_path FROM bookings WHERE id = ?", (booking_id,)
            ).fetchone()
        finally:
            connection.close()
        form_path = Path(row["form_path"])
        self.assertTrue(form_path.is_file())

        self.assertEqual(
            self.client.delete(f"/api/admin/bookings/{booking_id}").status_code,
            401,
        )
        self.sign_in()
        deleted = self.client.delete(f"/api/admin/bookings/{booking_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.get_json(), {"deleted": True, "formDeleted": True})
        self.assertFalse(form_path.exists())
        self.assertEqual(
            self.client.get("/api/admin/bookings").get_json()["bookings"],
            [],
        )

    def test_booking_slots_helper_accepts_sqlite_text_and_postgres_json_values(self):
        slot_values = [self.slot]
        self.assertEqual(
            facility_app.slots_from_row({"slots": json.dumps(slot_values)}),
            slot_values,
        )
        self.assertEqual(
            facility_app.slots_from_row({"slots": slot_values}),
            slot_values,
        )

    def test_supabase_storage_uses_private_server_credentials(self):
        with patch.dict(
            os.environ,
            {
                "SUPABASE_URL": "https://project.example",
                "SUPABASE_SERVICE_ROLE_KEY": "server-only-test-key",
            },
        ), patch.object(facility_app, "urlopen") as storage_urlopen:
            response = self.calendar_response(b'{"Key":"booking-forms/form.pdf"}')
            storage_urlopen.return_value = response
            facility_app.supabase_storage_request(
                "POST", "FC-260930-ABC123/form.pdf", b"%PDF-1.4", "application/pdf"
            )

        request = storage_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://project.example/storage/v1/object/booking-forms/FC-260930-ABC123/form.pdf")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Apikey"), "server-only-test-key")
        self.assertEqual(request.get_header("X-upsert"), "false")
        self.assertEqual(request.data, b"%PDF-1.4")

    def test_supabase_form_helpers_use_remote_storage(self):
        with patch.object(facility_app, "use_supabase_storage", return_value=True), patch.object(
            facility_app, "supabase_storage_request", return_value=b"%PDF-1.4"
        ) as storage_request:
            stored_path = facility_app.store_booking_form(
                "FC-260930-ABC123/form.pdf", b"%PDF-1.4"
            )
            downloaded = facility_app.read_booking_form(stored_path)
            removed = facility_app.remove_booking_form(stored_path)

        self.assertEqual(stored_path, "FC-260930-ABC123/form.pdf")
        self.assertEqual(downloaded, b"%PDF-1.4")
        self.assertTrue(removed)
        self.assertEqual(
            [call.args[0] for call in storage_request.call_args_list],
            ["POST", "GET", "DELETE"],
        )

    def test_sqlite_migration_imports_bookings_idempotently(self):
        source_database = Path(self.storage.name) / "old.sqlite3"
        source_uploads = Path(self.storage.name) / "old-forms"
        source_uploads.mkdir()
        source_form = source_uploads / "stored-form.pdf"
        source_form.write_bytes(b"%PDF-1.4\nExisting form")
        source = sqlite3.connect(source_database)
        source.execute("""
            CREATE TABLE bookings (
                id TEXT PRIMARY KEY, created_at TEXT, user_name TEXT,
                pi_name TEXT, phone TEXT, email TEXT, department TEXT,
                specimen TEXT, notes TEXT, slots TEXT, status TEXT,
                form_name TEXT, form_path TEXT
            )
        """)
        source.execute(
            "INSERT INTO bookings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "FC-260930-ABC123",
                "2026-09-30T12:00:00+00:00",
                "Alex",
                "PI",
                "+91 98765 43210",
                "alex@example.edu",
                "Biology",
                "Cell suspension",
                "",
                json.dumps([self.slot]),
                "confirmed",
                "facility-form.pdf",
                str(source_form),
            ),
        )
        source.commit()
        source.close()

        with patch.object(facility_app, "use_supabase_storage", return_value=True), patch.object(
            facility_app, "supabase_storage_request"
        ) as storage_request:
            self.assertEqual(
                booking_migration.migrate(source_database, source_uploads),
                (1, 0),
            )
            self.assertEqual(
                booking_migration.migrate(source_database, source_uploads),
                (0, 1),
            )

        connection = facility_app.booking_connection()
        try:
            row = connection.execute(
                "SELECT id, form_path FROM bookings WHERE id = ?",
                ("FC-260930-ABC123",),
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row["form_path"], "FC-260930-ABC123/stored-form.pdf")
        self.assertEqual(storage_request.call_count, 1)
        self.assertTrue(storage_request.call_args.kwargs["upsert"])

    def test_postgres_adapter_translates_queries_and_adapts_json_slots(self):
        class JsonbValue:
            def __init__(self, value):
                self.value = value

        class Cursor:
            pass

        class Connection:
            def __init__(self):
                self.calls = []

            def execute(self, statement, parameters=()):
                self.calls.append((statement, parameters))
                return Cursor()

        raw_connection = Connection()
        connection = facility_app.PostgresBookingConnection(
            raw_connection, JsonbValue, RuntimeError, "public"
        )
        values = [
            "FC-260930-ABC123",
            "now",
            "Alex",
            "PI",
            "phone",
            "email",
            "department",
            "specimen",
            "notes",
            json.dumps([self.slot]),
            "confirmed",
            "form.pdf",
            "FC-260930-ABC123/form.pdf",
        ]
        connection.execute(
            """INSERT INTO bookings (
                id, created_at, user_name, pi_name, phone, email, department,
                specimen, notes, slots, status, form_name, form_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?)""",
            values,
        )

        statement, parameters = raw_connection.calls[0]
        self.assertIn("VALUES (%s, %s, %s", statement)
        self.assertIsInstance(parameters[9], JsonbValue)
        self.assertEqual(parameters[9].value, [self.slot])

    def test_production_requires_database_url_instead_of_falling_back_to_sqlite(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}, clear=True):
            with self.assertRaises(facility_app.BookingConfigurationError):
                facility_app.booking_connection()

    def test_calendar_shows_brown_bear_when_supabase_persistence_is_unconfigured(self):
        event = {
            "date": "2026-09-30",
            "time": "09:00 AM - 10:00 AM",
            "title": "Research A",
            "instrument": "CytoFLEX LX",
            "color": "purple",
        }
        with patch.dict(
            os.environ,
            {"APP_ENV": "production", "DATABASE_URL": "postgresql://example"},
            clear=True,
        ), patch.object(facility_app, "fetch_brown_bear_month", return_value=[event]):
            response = self.client.get("/api/calendar?month=2026-09")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            payload["events"][0],
            {**event, "source": "calendar"},
        )
        self.assertFalse(payload["portalBookingsAvailable"])
        self.assertIn("only Brown Bear events are shown", payload["portalBookingsWarning"])

    def test_calendar_reports_portal_booking_data_unavailable_on_database_failure(self):
        event = {
            "date": "2026-09-30",
            "time": "09:00 AM - 10:00 AM",
            "title": "Research A",
            "instrument": "CytoFLEX LX",
            "color": "purple",
        }
        with patch.object(
            facility_app, "fetch_brown_bear_month", return_value=[event]
        ), patch.object(
            facility_app,
            "booking_connection",
            side_effect=facility_app.BookingDatabaseError,
        ):
            response = self.client.get("/api/calendar?month=2026-09")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            [item["title"] for item in payload["events"]],
            ["Research A"],
        )
        self.assertFalse(payload["portalBookingsAvailable"])

    def test_booking_rejects_weekend_sessions(self):
        saturday = facility_app.facility_today()
        while saturday.weekday() != 5:
            saturday += timedelta(days=1)
        response = self.client.post(
            "/api/bookings",
            data=self.booking_data({
                **self.slot,
                "date": saturday.isoformat(),
            }),
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_login_rejects_incorrect_password(self):
        response = self.client.post("/api/admin/login", json={"password": "wrong"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get("/api/admin/bookings").status_code, 401)

    def test_live_calendar_maps_brown_bear_categories_to_instrument_colors(self):
        calendar_html = b"""
        <table class="CalBlock">
          <tr class="DayHeaderRow"><td class="DayHeader"><a href="?Op=ShowDay;Date=2026-09-30">30</a></td></tr>
          <tr class="DayRow"><td>
            <div class="CalEvent c_CYTOFLEX" style="color:#50FF24"><div class="TimeLabel">09:00 AM - 10:00 AM</div><div class="EventLink"><a>Research A</a></div></div>
            <div class="CalEvent c_SYMPHONY" style="color:#50FF24"><div class="TimeLabel">10:00 AM - 11:00 AM</div><div class="EventLink"><a>Research B</a></div></div>
            <div class="CalEvent c_ARIA" style="color:#50FF24"><div class="TimeLabel">11:00 AM - 12:00 PM</div><div class="EventLink"><a>Research C</a></div></div>
            <div class="CalEvent c_DISCOVER" style="color:#50FF24"><div class="TimeLabel">12:00 PM - 01:00 PM</div><div class="EventLink"><a>Research D</a></div></div>
            <div class="CalEvent c_HOLIDAY" style="color:#50FF24"><div class="TimeLabel"></div><div class="EventLink"><a>Facility holiday</a></div></div>
          </td></tr>
        </table>
        """
        with patch.object(
            facility_app, "urlopen", return_value=self.calendar_response(calendar_html)
        ) as fetch_calendar:
            result = self.client.get("/api/calendar?month=2026-09")

        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            fetch_calendar.call_args.args[0].get_header("Cache-control"),
            "no-cache",
        )
        events = result.get_json()["events"]
        self.assertEqual(
            [(event["instrument"], event["color"]) for event in events],
            [
                ("CytoFLEX LX", "purple"),
                ("Symphony A1", "blue"),
                ("FACSAria™ Fusion", "gray"),
                ("Discover S8 Spectral Flow Cytometer", "teal"),
                ("", "neutral"),
            ],
        )
        self.assertEqual([event["title"] for event in events][-1], "Facility holiday")


if __name__ == "__main__":
    unittest.main()
