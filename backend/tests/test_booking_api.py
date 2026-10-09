import io
import json
import os
import sqlite3
from contextlib import closing
from datetime import date, timedelta
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
        self.workshop_uploads_patch = patch.object(
            facility_app, "WORKSHOP_UPLOADS", storage_path / "workshop-images"
        )
        self.database_patch.start()
        self.uploads_patch.start()
        self.workshop_uploads_patch.start()
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
        self.client.environ_base["HTTP_ORIGIN"] = "http://localhost"
        self.csrf_token = ""
        slot_date = facility_app.facility_today() + timedelta(days=1)
        while slot_date.weekday() >= 5:
            slot_date += timedelta(days=1)
        self.slot = {
            "instrument": facility_app.load_json("instruments.json")[0]["name"],
            "date": slot_date.isoformat(),
            "time": "10:00-11:00",
        }

    def tearDown(self):
        self.password_patch.stop()
        self.workshop_uploads_patch.stop()
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
        response = self.client.post(
            "/api/admin/login",
            json={"password": "test-admin-password"},
        )
        if response.status_code == 200:
            self.csrf_token = response.get_json()["csrfToken"]
        return response

    def admin_headers(self):
        return {"X-CSRF-Token": self.csrf_token}

    def test_booking_reserves_slot_and_admin_can_cancel_and_restore(self):
        created = self.client.post("/api/bookings", data=self.booking_data())
        self.assertEqual(created.status_code, 201)
        booking = created.get_json()
        self.assertEqual(booking["status"], "pending")
        self.assertFalse(booking["notifications"]["user"]["sent"])

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
        self.assertEqual(booked_slot["status"], "pending")
        self.assertEqual(booked_slot["userName"], "Alex Researcher")
        self.assertEqual(booked_slot["title"], "Alex Researcher · Under review")
        calendar = self.client.get(
            f"/api/calendar?month={self.slot['date'][:7]}"
        ).get_json()
        portal_events = [
            event for event in calendar["events"] if event["source"] == "portal"
        ]
        self.assertEqual(len(portal_events), 1)
        self.assertEqual(portal_events[0]["userName"], "Alex Researcher")
        self.assertEqual(portal_events[0]["title"], "Alex Researcher · Under review")
        conflict = self.client.post("/api/bookings", data=self.booking_data())
        self.assertEqual(conflict.status_code, 409)

        self.assertEqual(self.client.get("/api/admin/bookings").status_code, 401)
        self.assertEqual(self.sign_in().status_code, 200)
        listing = self.client.get("/api/admin/bookings")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.get_json()["bookings"][0]["userName"], "Alex Researcher")
        self.assertEqual(listing.get_json()["bookings"][0]["status"], "pending")
        self.assertEqual(listing.get_json()["bookings"][0]["slots"][0]["color"], "purple")

        download = self.client.get(f"/api/admin/bookings/{booking['id']}/form")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.data, b"%PDF-1.4\nTest form")
        download.close()

        with patch.object(
            facility_app, "send_booking_email", return_value={"sent": True, "error": None}
        ) as send_email:
            accepted = self.client.patch(
                f"/api/admin/bookings/{booking['id']}",
                json={"status": "confirmed"},
                headers=self.admin_headers(),
            )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.get_json()["booking"]["status"], "confirmed")
        self.assertTrue(accepted.get_json()["notification"]["sent"])
        send_email.assert_called_once()

        cancelled = self.client.patch(
            f"/api/admin/bookings/{booking['id']}",
            json={"status": "cancelled"},
            headers=self.admin_headers(),
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
            f"/api/admin/bookings/{booking['id']}",
            json={"status": "confirmed"},
            headers=self.admin_headers(),
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.client.get("/api/admin/bookings").status_code, 200)
        self.assertEqual(
            self.client.post(
                "/api/admin/logout", headers=self.admin_headers()
            ).status_code,
            200,
        )
        self.assertEqual(self.client.get("/api/admin/bookings").status_code, 401)
        self.sign_in()
        self.client.patch(
            f"/api/admin/bookings/{replacement.get_json()['id']}",
            json={"status": "cancelled"},
            headers=self.admin_headers(),
        )
        with patch.object(
            facility_app, "send_booking_email", return_value={"sent": False, "error": "SMTP unavailable"}
        ):
            restored = self.client.patch(
                f"/api/admin/bookings/{booking['id']}",
                json={"status": "confirmed"},
                headers=self.admin_headers(),
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
        if current.hour < 10:
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
        self.assertTrue(any(
            slot["date"] == today_slot["date"] and slot["time"] == started_time
            for slot in availability.get_json()["unavailable"]
        ))

    def test_booking_slots_respect_two_operator_limit(self):
        instruments = facility_app.load_json("instruments.json")
        first = self.slot
        second = {
            **self.slot,
            "instrument": next(
                item["name"] for item in instruments
                if item["type"] == "Analyzer" and item["name"] != first["instrument"]
            ),
        }
        third = {
            **self.slot,
            "instrument": next(
                item["name"] for item in instruments if item["type"] == "Sorter"
            ),
        }
        self.assertEqual(
            self.client.post("/api/bookings", data=self.booking_data(first)).status_code,
            201,
        )
        self.assertEqual(
            self.client.post("/api/bookings", data=self.booking_data(second)).status_code,
            201,
        )
        response = self.client.post("/api/bookings", data=self.booking_data(third))
        self.assertEqual(response.status_code, 409)
        self.assertIn("Only two instruments", response.get_json()["error"])

    def test_sorter_booking_blocks_following_slot_for_cleaning(self):
        sorter = next(
            item["name"] for item in facility_app.load_json("instruments.json")
            if item["type"] == "Sorter"
        )
        booked_slot = {**self.slot, "instrument": sorter}
        created = self.client.post(
            "/api/bookings", data=self.booking_data(booked_slot)
        )
        self.assertEqual(created.status_code, 201)

        availability = self.client.get(
            f"/api/booking-availability?start={self.slot['date']}&end={self.slot['date']}"
        ).get_json()
        cleaning_slot = next(
            item for item in availability["booked"]
            if item["instrument"] == sorter and item["time"] == "11:00-12:00"
        )
        self.assertEqual(cleaning_slot["source"], "cleaning")
        self.assertEqual(cleaning_slot["title"], "Blocked for cleaning")

        following_sorter_slot = {
            **booked_slot,
            "time": "11:00-12:00",
        }
        blocked = self.client.post(
            "/api/bookings", data=self.booking_data(following_sorter_slot)
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("blocked for cleaning", blocked.get_json()["error"])

    def test_adjacent_sorter_slots_can_be_booked_with_cleaning_after_the_run(self):
        sorter = next(
            item["name"] for item in facility_app.load_json("instruments.json")
            if item["type"] == "Sorter"
        )
        data = self.booking_data()
        data["slots"] = json.dumps([
            {**self.slot, "instrument": sorter, "time": "10:00-11:00"},
            {**self.slot, "instrument": sorter, "time": "11:00-12:00"},
        ])
        response = self.client.post("/api/bookings", data=data)
        self.assertEqual(response.status_code, 201, response.get_json())

        availability = self.client.get(
            f"/api/booking-availability?start={self.slot['date']}&end={self.slot['date']}"
        ).get_json()
        self.assertIn(
            {
                "instrument": sorter,
                "date": self.slot["date"],
                "time": "12:00-13:00",
                "color": next(
                    item["color"] for item in facility_app.load_json("instruments.json")
                    if item["name"] == sorter
                ),
                "source": "cleaning",
                "title": "Blocked for cleaning",
            },
            availability["booked"],
        )
        third_slot = {
            **self.slot,
            "instrument": sorter,
            "time": "12:00-13:00",
        }
        blocked = self.client.post(
            "/api/bookings", data=self.booking_data(third_slot)
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertIn("blocked for cleaning", blocked.get_json()["error"])

    def test_sorter_cleaning_does_not_cross_the_lunch_gap(self):
        sorter = next(
            item["name"] for item in facility_app.load_json("instruments.json")
            if item["type"] == "Sorter"
        )
        afternoon_slot = {
            **self.slot,
            "instrument": sorter,
            "time": "14:00-15:00",
        }
        response = self.client.post(
            "/api/bookings", data=self.booking_data(afternoon_slot)
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        availability = self.client.get(
            f"/api/booking-availability?start={self.slot['date']}&end={self.slot['date']}"
        ).get_json()
        self.assertFalse(any(
            slot["instrument"] == sorter and slot["time"] == "14:00-15:00"
            and slot["source"] == "cleaning"
            for slot in availability["booked"]
        ))

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
                    "time": "10:00-11:00",
                    "color": "purple",
                    "source": "calendar",
                    "title": "Existing CytoFLEX session",
                },
                booked,
            )
            self.assertNotIn(
                "11:00-12:00",
                [slot["time"] for slot in booked if slot["instrument"] == self.slot["instrument"]],
            )
            other_instrument = next(
                item["name"] for item in facility_app.load_json("instruments.json")
                if item["name"] != self.slot["instrument"]
            )
            self.assertNotIn(
                (other_instrument, "10:00-11:00"),
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
                ["10:00-11:00", "11:00-12:00", "12:00-13:00"],
            )
            conflict = self.client.post(
                "/api/bookings", data=self.booking_data()
            )
        self.assertEqual(conflict.status_code, 409)
        self.assertIn("facility calendar", conflict.get_json()["error"])

    def test_brown_bear_event_date_blocks_the_matching_instrument_slot(self):
        event_date = self.slot["date"]
        calendar_date = event_date.replace("-", "/")
        calendar_html = f"""
        <table class="CalBlock">
          <tr class="DayHeaderRow">
            <td class="DayHeader"><a href="?Op=ShowDay;Date={event_date}">6</a></td>
          </tr>
          <tr class="DayRow"><td>
            <div class="CalEvent c_SYMPHONY">
              <div class="TimeLabel">2:00 PM - 3:00 PM</div>
              <div class="EventLink"><a href="JavaScript:PopupWindow ('flow_cytometry', '{calendar_date}', '123456789', '', '250', '350')">Aagosh/DPN</a></div>
            </div>
          </td></tr>
        </table>
        """.encode()
        symphony_slot = {
            "instrument": "Symphony A1",
            "date": event_date,
            "time": "14:00-15:00",
        }
        with patch.object(
            facility_app,
            "urlopen",
            return_value=self.calendar_response(calendar_html),
        ):
            availability = self.client.get(
                f"/api/booking-availability?start={event_date}&end={event_date}"
            )
            booking = self.client.post(
                "/api/bookings", data=self.booking_data(symphony_slot)
            )

        self.assertEqual(availability.status_code, 200)
        matching = [
            slot for slot in availability.get_json()["booked"]
            if slot["instrument"] == "Symphony A1"
        ]
        self.assertEqual(
            [(slot["date"], slot["time"], slot["title"]) for slot in matching],
            [(event_date, "14:00-15:00", "Aagosh/DPN")],
        )
        self.assertEqual(booking.status_code, 409)
        self.assertIn("facility calendar", booking.get_json()["error"])

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

        replacement_date = date.fromisoformat(self.slot["date"]) + timedelta(days=1)
        while (
            replacement_date.weekday() >= 5
            or facility_app.iisc_holiday_for_date(replacement_date.isoformat())
        ):
            replacement_date += timedelta(days=1)
        replacement_slot = {
            **self.slot,
            "date": replacement_date.isoformat(),
            "time": "11:00-12:00",
        }
        updated = self.client.put(
            f"/api/admin/bookings/{booking_id}/slots",
            json={"slots": [replacement_slot]},
            headers=self.admin_headers(),
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

    def test_admin_can_create_and_edit_all_booking_details(self):
        self.sign_in()
        values = {
            "userName": "Staff Added",
            "piName": "Dr. Example",
            "phone": "+91 98765 43210",
            "email": "staff-added@example.edu",
            "department": "Biological Sciences",
            "specimen": "Cell suspension",
            "notes": "Created by staff",
            "slots": [self.slot],
        }
        with patch.object(
            facility_app, "send_booking_email", return_value={"sent": True, "error": None}
        ):
            created = self.client.post(
                "/api/admin/bookings",
                json=values,
                headers=self.admin_headers(),
            )
        self.assertEqual(created.status_code, 201)
        booking = created.get_json()["booking"]
        self.assertEqual(booking["status"], "confirmed")
        self.assertFalse(booking["hasForm"])
        self.assertTrue(created.get_json()["notification"]["sent"])

        new_date = facility_app.facility_today() + timedelta(days=3)
        while new_date.weekday() >= 5:
            new_date += timedelta(days=1)
        values.update({
            "userName": "Updated Staff Booking",
            "email": "updated@example.edu",
            "notes": "Updated notes",
            "slots": [{**self.slot, "date": new_date.isoformat()}],
        })
        updated = self.client.put(
            f"/api/admin/bookings/{booking['id']}",
            json=values,
            headers=self.admin_headers(),
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["booking"]["userName"], "Updated Staff Booking")
        self.assertEqual(updated.get_json()["booking"]["email"], "updated@example.edu")
        self.assertEqual(updated.get_json()["booking"]["notes"], "Updated notes")
        self.assertEqual(updated.get_json()["booking"]["slots"][0]["date"], new_date.isoformat())

    def test_admin_created_booking_appears_in_public_calendar_and_availability(self):
        self.sign_in()
        slot = {
            "instrument": "CytoFLEX LX",
            "date": "2026-10-30",
            "time": "14:00-15:00",
        }
        created = self.client.post(
            "/api/admin/bookings",
            json={
                "userName": "Shradha",
                "piName": "Dr. Example",
                "phone": "+91 98765 43210",
                "email": "shradha@example.edu",
                "department": "Biological Sciences",
                "specimen": "Cell suspension",
                "notes": "Manual booking",
                "slots": [slot],
            },
            headers=self.admin_headers(),
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()["booking"]["status"], "confirmed")

        calendar = self.client.get("/api/calendar?month=2026-10").get_json()
        calendar_bookings = [
            event for event in calendar["events"]
            if event["source"] == "portal"
            and event["date"] == "2026-10-30"
            and event["instrument"] == "CytoFLEX LX"
        ]
        self.assertEqual(len(calendar_bookings), 1)
        self.assertEqual(calendar_bookings[0]["time"], "14:00-15:00")
        self.assertEqual(calendar_bookings[0]["title"], "Shradha")
        self.assertEqual(calendar_bookings[0]["userName"], "Shradha")

        availability = self.client.get(
            "/api/booking-availability?start=2026-10-01&end=2026-10-31"
        ).get_json()
        self.assertIn(
            {
                "instrument": "CytoFLEX LX",
                "date": "2026-10-30",
                "time": "14:00-15:00",
                "source": "portal",
                "status": "confirmed",
                "userName": "Shradha",
            },
            [
                {key: item[key] for key in (
                    "instrument", "date", "time", "source", "status", "userName"
                )}
                for item in availability["booked"]
                if item.get("date") == "2026-10-30"
                and item.get("instrument") == "CytoFLEX LX"
            ],
        )

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
                headers=self.admin_headers(),
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
        deleted = self.client.delete(
            f"/api/admin/bookings/{booking_id}",
            headers=self.admin_headers(),
        )
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

    def test_booking_schedule_and_legacy_slot_expansion(self):
        self.assertEqual(
            facility_app.BOOKING_SLOTS,
            (
                "10:00-11:00",
                "11:00-12:00",
                "12:00-13:00",
                "14:00-15:00",
                "15:00-16:00",
                "16:00-17:00",
            ),
        )
        instruments = {
            item["name"]: item for item in facility_app.load_json("instruments.json")
        }
        migrated = facility_app.expand_stored_slots(
            [{
                **self.slot,
                "time": "09:00-11:00",
            }, {
                **self.slot,
                "time": "11:00-13:00",
            }],
            instruments,
        )
        self.assertEqual(
            [slot["time"] for slot in migrated],
            ["10:00-11:00", "11:00-12:00", "12:00-13:00"],
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

        connection.execute(
            """UPDATE bookings SET user_name = ?, pi_name = ?, phone = ?, email = ?,
                department = ?, specimen = ?, notes = ?, slots = ? WHERE id = ?""",
            ["Alex", "PI", "phone", "email", "dept", "specimen", "notes",
             json.dumps([self.slot]), "FC-260930-ABC123"],
        )
        statement, parameters = raw_connection.calls[-1]
        self.assertIn("slots = %s", statement)
        self.assertIsInstance(parameters[7], JsonbValue)

        connection.execute("BEGIN IMMEDIATE")
        self.assertTrue(any(
            "pg_advisory_xact_lock" in statement
            for statement, _ in raw_connection.calls
        ))

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
        self.assertIn("Brown Bear entries and IISc holidays are shown", payload["portalBookingsWarning"])

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
            [item["title"] for item in payload["events"] if item["source"] == "calendar"],
            ["Research A"],
        )
        self.assertTrue(any(event["source"] == "holiday" for event in payload["events"]))
        self.assertFalse(payload["portalBookingsAvailable"])

    def test_booking_allows_saturday_and_rejects_sunday_sessions(self):
        saturday = facility_app.facility_today()
        while saturday.weekday() != 5 or saturday == facility_app.facility_today():
            saturday += timedelta(days=1)
        saturday_response = self.client.post(
            "/api/bookings",
            data=self.booking_data({
                **self.slot,
                "date": saturday.isoformat(),
            }),
        )
        self.assertEqual(saturday_response.status_code, 201)

        sunday_response = self.client.post(
            "/api/bookings",
            data=self.booking_data({
                **self.slot,
                "date": (saturday + timedelta(days=1)).isoformat(),
            }),
        )
        self.assertEqual(sunday_response.status_code, 400)

    def test_supabase_booking_session_schema_allows_saturdays(self):
        migration_dir = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
        initial_schema = (
            migration_dir / "20260930120000_facility_booking_storage.sql"
        ).read_text(encoding="utf-8")
        saturday_migration = (
            migration_dir / "20261007130000_allow_saturday_booking_sessions.sql"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "check (extract(isodow from session_date) between 1 and 6)",
            initial_schema,
        )
        self.assertIn(
            "check (extract(isodow from session_date) between 1 and 6)",
            saturday_migration,
        )

    def test_booking_window_reaches_the_end_of_next_month_only(self):
        reference_date = facility_app.facility_today()
        window_end = facility_app.booking_window_end(reference_date)
        last_bookable_date = window_end
        while last_bookable_date.weekday() == 6:
            last_bookable_date -= timedelta(days=1)
        outside_window_date = window_end + timedelta(days=1)
        with patch.object(facility_app, "facility_today", return_value=reference_date):
            self.assertEqual(
                facility_app.booking_window_end(),
                window_end,
            )
            availability = self.client.get(
                "/api/booking-availability"
                f"?start={reference_date.isoformat()}&end={outside_window_date.isoformat()}"
            )
            last_day_booking = self.client.post(
                "/api/bookings",
                data=self.booking_data({
                    **self.slot,
                    "date": last_bookable_date.isoformat(),
                }),
            )
            outside_window_booking = self.client.post(
                "/api/bookings",
                data=self.booking_data({
                    **self.slot,
                    "date": outside_window_date.isoformat(),
                }),
            )
        self.assertEqual(availability.status_code, 200)
        availability_data = availability.get_json()
        self.assertTrue(any(
            item["date"] == outside_window_date.isoformat()
            and item["reason"] == "booking_window"
            for item in availability_data["unavailable"]
        ))
        next_sunday = reference_date
        while next_sunday.weekday() != 6:
            next_sunday += timedelta(days=1)
        self.assertTrue(any(
            item["date"] == next_sunday.isoformat()
            and item["reason"] == "weekend"
            for item in availability_data["unavailable"]
        ))
        self.assertEqual(last_day_booking.status_code, 201, last_day_booking.get_json())
        self.assertEqual(outside_window_booking.status_code, 400)

    def test_iisc_holidays_are_shown_and_blocked_but_restricted_dates_are_not(self):
        holiday_date = "2026-12-25"
        with patch.object(
            facility_app, "facility_today", return_value=date(2026, 10, 1)
        ):
            availability = self.client.get(
                f"/api/booking-availability?start={holiday_date}&end={holiday_date}"
            )
            self.assertEqual(availability.status_code, 200)
            payload = availability.get_json()
            self.assertEqual(
                payload["holidays"],
                [{"date": holiday_date, "name": "Christmas Day"}],
            )
            self.assertEqual(
                {slot["reason"] for slot in payload["unavailable"]},
                {"holiday"},
            )
            self.assertIn("2026", payload["holidayCalendarYears"])
            calendar = self.client.get("/api/calendar?month=2026-12").get_json()
            self.assertEqual(
                calendar["holidaySource"],
                facility_app.iisc_holiday_calendar()["source"],
            )
            christmas = [
                event for event in calendar["events"]
                if event["source"] == "holiday" and event["date"] == holiday_date
            ]
            self.assertEqual(
                christmas[0]["title"],
                "IISc Holiday · Christmas Day",
            )
            self.assertEqual(christmas[0]["time"], "All day")
            restricted_date = self.client.get(
                "/api/booking-availability?start=2026-01-01&end=2026-01-01"
            ).get_json()
            self.assertEqual(restricted_date["holidays"], [])
            self.assertNotIn(
                "holiday",
                {slot["reason"] for slot in restricted_date["unavailable"]},
            )

            response = self.client.post(
                "/api/bookings",
                data=self.booking_data({**self.slot, "date": holiday_date}),
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("Christmas Day", response.get_json()["error"])

    def test_brown_bear_holiday_entry_is_hidden_and_admin_can_override(self):
        holiday_date = "2026-12-25"
        brown_bear_holiday = {
            "date": holiday_date,
            "time": "",
            "title": "CHRISTMAS",
            "instrument": "",
            "color": "neutral",
        }
        with patch.object(
            facility_app, "fetch_brown_bear_month", return_value=[brown_bear_holiday]
        ):
            calendar = self.client.get("/api/calendar?month=2026-12").get_json()
            day_events = [
                event for event in calendar["events"] if event["date"] == holiday_date
            ]
            self.assertEqual(
                [(event["source"], event["title"]) for event in day_events],
                [("holiday", "IISc Holiday · Christmas Day")],
            )
            availability = self.client.get(
                f"/api/booking-availability?start={holiday_date}&end={holiday_date}"
            ).get_json()
            self.assertFalse(any(
                slot.get("source") == "calendar" for slot in availability["booked"]
            ))

            self.sign_in()
            admin_response = self.client.post(
                "/api/admin/bookings",
                json={
                    "userName": "Emergency session",
                    "piName": "Dr. Example",
                    "phone": "+91 98765 43210",
                    "email": "emergency@example.edu",
                    "department": "Biological Sciences",
                    "specimen": "Cell suspension",
                    "notes": "Emergency facility session",
                    "slots": [{**self.slot, "date": holiday_date}],
                },
                headers=self.admin_headers(),
            )
        self.assertEqual(admin_response.status_code, 201)
        self.assertEqual(
            admin_response.get_json()["booking"]["slots"][0]["date"],
            holiday_date,
        )
        rescheduled = self.client.put(
            f"/api/admin/bookings/{admin_response.get_json()['booking']['id']}/slots",
            json={"slots": [{**self.slot, "date": holiday_date}]},
            headers=self.admin_headers(),
        )
        self.assertEqual(rescheduled.status_code, 200)

    def test_unknown_iisc_holiday_year_is_not_bookable(self):
        future_date = "2027-01-01"
        with patch.object(
            facility_app, "facility_today", return_value=date(2026, 10, 5)
        ):
            availability = self.client.get(
                f"/api/booking-availability?start={future_date}&end={future_date}"
            )
            self.assertEqual(availability.status_code, 200)
            self.assertEqual(
                {slot["reason"] for slot in availability.get_json()["unavailable"]},
                {"holiday_calendar_unavailable"},
            )
            response = self.client.post(
                "/api/bookings",
                data=self.booking_data({**self.slot, "date": future_date}),
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("2027", response.get_json()["error"])

    def test_admin_workshop_closure_blocks_selected_slots_and_updates_calendar(self):
        self.assertEqual(
            self.client.get("/api/admin/calendar-closures").status_code, 401
        )
        self.sign_in()
        closure_data = {
            "type": "workshop",
            "startDate": self.slot["date"],
            "endDate": self.slot["date"],
            "scope": "specific",
            "slotTimes": ["10:00-11:00"],
            "remark": "Laser safety workshop",
        }
        no_csrf = self.client.post(
            "/api/admin/calendar-closures", json=closure_data
        )
        self.assertEqual(no_csrf.status_code, 401)

        created = self.client.post(
            "/api/admin/calendar-closures",
            json=closure_data,
            headers=self.admin_headers(),
        )
        self.assertEqual(created.status_code, 201)
        closure = created.get_json()["closure"]
        self.assertEqual(closure["type"], "workshop")
        self.assertEqual(closure["slotTimes"], ["10:00-11:00"])

        availability = self.client.get(
            f"/api/booking-availability?start={self.slot['date']}&end={self.slot['date']}"
        ).get_json()
        blocked = next(
            slot for slot in availability["unavailable"]
            if slot["time"] == "10:00-11:00"
        )
        self.assertEqual(blocked["reason"], "workshop_closure")
        self.assertEqual(blocked["remark"], "Laser safety workshop")
        self.assertNotIn(
            ("11:00-12:00", "workshop_closure"),
            {(slot["time"], slot["reason"]) for slot in availability["unavailable"]},
        )

        calendar = self.client.get(
            f"/api/calendar?month={self.slot['date'][:7]}"
        ).get_json()
        closure_events = [
            event for event in calendar["events"]
            if event["source"] == "admin_closure"
        ]
        self.assertEqual(len(closure_events), 1)
        self.assertEqual(closure_events[0]["title"], "Laser safety workshop")
        self.assertEqual(closure_events[0]["eventType"], "workshop")
        self.assertEqual(closure_events[0]["time"], "10:00-11:00")
        admin_calendar = self.client.get(
            f"/api/admin/calendar?month={self.slot['date'][:7]}"
        )
        self.assertEqual(admin_calendar.status_code, 200)
        self.assertTrue(any(
            event["source"] == "admin_closure"
            and event["title"] == "Laser safety workshop"
            for event in admin_calendar.get_json()["events"]
        ))

        rejected_booking = self.client.post(
            "/api/bookings",
            data=self.booking_data({**self.slot, "time": "10:00-11:00"}),
        )
        self.assertEqual(rejected_booking.status_code, 409)
        self.assertIn("Laser safety workshop", rejected_booking.get_json()["error"])

        listed = self.client.get("/api/admin/calendar-closures").get_json()["closures"]
        self.assertEqual([item["id"] for item in listed], [closure["id"]])
        removed = self.client.delete(
            f"/api/admin/calendar-closures/{closure['id']}",
            headers=self.admin_headers(),
        )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(
            self.client.delete(
                f"/api/admin/calendar-closures/{closure['id']}",
                headers=self.admin_headers(),
            ).status_code,
            404,
        )

    def test_admin_exception_closure_can_block_all_slots_across_date_range(self):
        self.sign_in()
        second_date = date.fromisoformat(self.slot["date"]) + timedelta(days=1)
        created = self.client.post(
            "/api/admin/calendar-closures",
            json={
                "type": "exception",
                "startDate": self.slot["date"],
                "endDate": second_date.isoformat(),
                "scope": "all",
                "slotTimes": [],
                "remark": "Facility maintenance",
            },
            headers=self.admin_headers(),
        )
        self.assertEqual(created.status_code, 201)
        for slot_date in (self.slot["date"], second_date.isoformat()):
            availability = self.client.get(
                f"/api/booking-availability?start={slot_date}&end={slot_date}"
            ).get_json()
            closure_slots = [
                slot for slot in availability["unavailable"]
                if slot["reason"] == "exception_closure"
            ]
            self.assertEqual(len(closure_slots), len(facility_app.BOOKING_SLOTS))

    def test_admin_events_are_editable_and_publicly_listed_until_their_end_date(self):
        self.assertEqual(self.client.get("/api/admin/events").status_code, 401)
        self.assertEqual(self.client.get("/api/events").get_json(), {"events": []})
        self.sign_in()
        event_payload = {
            "category": "workshop",
            "title": "Introduction to Flow Cytometry",
            "startDate": self.slot["date"],
            "endDate": self.slot["date"],
            "summary": "A hands-on facility workshop.",
            "description": "Learn cytometry fundamentals and instrument setup.",
            "linkLabel": "View workshop brochure",
            "linkUrl": "https://example.edu/workshops/flow-cytometry.pdf",
        }
        no_csrf = self.client.post("/api/admin/events", json=event_payload)
        self.assertEqual(no_csrf.status_code, 401)

        created = self.client.post(
            "/api/admin/events",
            json=event_payload,
            headers=self.admin_headers(),
        )
        self.assertEqual(created.status_code, 201)
        event = created.get_json()["event"]
        self.assertEqual(event["title"], event_payload["title"])
        public_events = self.client.get("/api/events")
        self.assertEqual(public_events.status_code, 200)
        self.assertEqual(public_events.get_json()["events"], [event])

        updated_payload = {
            **event_payload,
            "category": "event",
            "summary": "Updated facility seminar announcement.",
            "linkLabel": "Register",
            "linkUrl": "/workshops.html#registration",
        }
        updated = self.client.put(
            f"/api/admin/events/{event['id']}",
            json=updated_payload,
            headers=self.admin_headers(),
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["event"]["category"], "event")
        self.assertEqual(
            updated.get_json()["event"]["linkUrl"],
            "/workshops.html#registration",
        )
        self.assertEqual(
            self.client.get("/api/events").get_json()["events"][0]["summary"],
            "Updated facility seminar announcement.",
        )

        rejected = self.client.post(
            "/api/admin/events",
            json={**event_payload, "linkUrl": "javascript:alert(1)"},
            headers=self.admin_headers(),
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(
            self.client.put(
                "/api/admin/events/missing-event",
                json=event_payload,
                headers=self.admin_headers(),
            ).status_code,
            404,
        )

        deleted = self.client.delete(
            f"/api/admin/events/{event['id']}",
            headers=self.admin_headers(),
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/events").get_json(), {"events": []})
        self.assertEqual(
            self.client.delete(
                f"/api/admin/events/{event['id']}",
                headers=self.admin_headers(),
            ).status_code,
            404,
        )

    def test_admin_events_hide_expired_items_from_public_pages(self):
        self.sign_in()
        yesterday = facility_app.facility_today() - timedelta(days=1)
        event_payload = {
            "category": "event",
            "title": "Past seminar",
            "startDate": yesterday.isoformat(),
            "endDate": yesterday.isoformat(),
            "summary": "This event is in the archive.",
            "description": "Past event details.",
            "linkLabel": "View notes",
            "linkUrl": "https://example.edu/seminar",
        }
        self.assertEqual(
            self.client.post(
                "/api/admin/events",
                json=event_payload,
                headers=self.admin_headers(),
            ).status_code,
            201,
        )
        self.assertEqual(self.client.get("/api/events").get_json(), {"events": []})
        admin_events = self.client.get("/api/admin/events").get_json()["events"]
        self.assertEqual(len(admin_events), 1)
        self.assertEqual(admin_events[0]["title"], "Past seminar")

    def test_admin_can_update_workshop_summary_and_photo(self):
        self.assertEqual(
            self.client.get("/api/admin/workshop-content").status_code, 401
        )
        archive = self.client.get("/api/workshops/archive").get_json()
        self.assertEqual(archive["summary"], facility_app.ARCHIVED_WORKSHOP_SUMMARY)
        self.assertIsNone(archive["imageUrl"])

        self.sign_in()
        workshop_payload = {
            "category": "workshop",
            "title": "Introduction to Flow Cytometry",
            "startDate": self.slot["date"],
            "endDate": self.slot["date"],
            "summary": "A hands-on facility workshop.",
            "description": "Learn cytometry fundamentals and instrument setup.",
            "linkLabel": "View workshop brochure",
            "linkUrl": "https://example.edu/workshops/flow-cytometry.pdf",
        }
        created = self.client.post(
            "/api/admin/events",
            json=workshop_payload,
            headers=self.admin_headers(),
        )
        self.assertEqual(created.status_code, 201)
        workshop_id = created.get_json()["event"]["id"]
        managed_content = self.client.get(
            "/api/admin/workshop-content"
        ).get_json()
        self.assertEqual(
            [item["id"] for item in managed_content["events"]],
            [workshop_id],
        )

        workshop_photo = b"\x89PNG\r\n\x1a\nworkshop-image"
        updated = self.client.put(
            f"/api/admin/workshop-content/{workshop_id}",
            data={
                "summary": "Updated workshop summary.",
                "photo": (io.BytesIO(workshop_photo), "workshop.png"),
            },
            headers=self.admin_headers(),
        )
        self.assertEqual(updated.status_code, 200)
        event = self.client.get("/api/events").get_json()["events"][0]
        self.assertEqual(event["summary"], "Updated workshop summary.")
        self.assertEqual(event["imageUrl"], f"/api/workshop-images/{workshop_id}")
        photo_response = self.client.get(event["imageUrl"])
        self.assertEqual(photo_response.status_code, 200)
        self.assertEqual(photo_response.mimetype, "image/png")
        self.assertEqual(photo_response.data, workshop_photo)

        invalid_photo = self.client.put(
            f"/api/admin/workshop-content/{workshop_id}",
            data={
                "summary": "Valid summary.",
                "photo": (io.BytesIO(b"not an image"), "workshop.txt"),
            },
            headers=self.admin_headers(),
        )
        self.assertEqual(invalid_photo.status_code, 400)

        archive_photo = b"\xff\xd8\xffarchived-photo"
        archive_update = self.client.put(
            "/api/admin/workshop-content/archive",
            data={
                "summary": "Updated archive summary.",
                "photo": (io.BytesIO(archive_photo), "archive.jpg"),
            },
            headers=self.admin_headers(),
        )
        self.assertEqual(archive_update.status_code, 200)
        archive = self.client.get("/api/workshops/archive").get_json()
        self.assertEqual(archive["summary"], "Updated archive summary.")
        self.assertEqual(archive["imageUrl"], "/api/workshop-images/archive")
        archive_image = self.client.get(archive["imageUrl"])
        self.assertEqual(archive_image.mimetype, "image/jpeg")
        self.assertEqual(archive_image.data, archive_photo)

        remove_photo = self.client.put(
            "/api/admin/workshop-content/archive",
            data={
                "summary": "Summary without a photo.",
                "removePhoto": "true",
            },
            headers=self.admin_headers(),
        )
        self.assertEqual(remove_photo.status_code, 200)
        self.assertIsNone(
            self.client.get("/api/workshops/archive").get_json()["imageUrl"]
        )
        self.assertEqual(
            self.client.get("/api/workshop-images/archive").status_code, 404
        )

    def test_admin_gallery_uploads_public_photos_and_can_delete_them(self):
        self.assertEqual(self.client.get("/api/gallery").get_json(), {"items": []})
        self.assertEqual(self.client.get("/api/admin/gallery").status_code, 401)
        self.sign_in()

        photo = b"\x89PNG\r\n\x1a\ngallery-photo"
        gallery_metadata = {
            "eventName": "Flow Cytometry Workshop",
            "eventDate": self.slot["date"],
            "description": "Workshop participants",
        }
        unauthorized = self.client.post(
            "/api/admin/gallery",
            data={
                **gallery_metadata,
                "photo": (io.BytesIO(photo), "gallery.png"),
            },
        )
        self.assertEqual(unauthorized.status_code, 401)

        missing_photo = self.client.post(
            "/api/admin/gallery",
            data=gallery_metadata,
            headers=self.admin_headers(),
        )
        self.assertEqual(missing_photo.status_code, 400)
        invalid_description = self.client.post(
            "/api/admin/gallery",
            data={
                **{**gallery_metadata, "description": " "},
                "photo": (io.BytesIO(photo), "gallery.png"),
            },
            headers=self.admin_headers(),
        )
        self.assertEqual(invalid_description.status_code, 400)
        invalid_date = self.client.post(
            "/api/admin/gallery",
            data={
                **{**gallery_metadata, "eventDate": "2026-02-30"},
                "photo": (io.BytesIO(photo), "gallery.png"),
            },
            headers=self.admin_headers(),
        )
        self.assertEqual(invalid_date.status_code, 400)
        invalid_photo = self.client.post(
            "/api/admin/gallery",
            data={
                **gallery_metadata,
                "photo": (io.BytesIO(b"not an image"), "gallery.txt"),
            },
            headers=self.admin_headers(),
        )
        self.assertEqual(invalid_photo.status_code, 400)

        created = self.client.post(
            "/api/admin/gallery",
            data={
                **gallery_metadata,
                "photo": (io.BytesIO(photo), "gallery.png"),
            },
            headers=self.admin_headers(),
        )
        self.assertEqual(created.status_code, 201)
        item = created.get_json()["item"]
        self.assertEqual(item["eventName"], gallery_metadata["eventName"])
        self.assertEqual(item["eventDate"], gallery_metadata["eventDate"])
        self.assertEqual(item["description"], "Workshop participants")
        self.assertEqual(item["imageUrl"], f"/api/gallery-images/{item['id']}")

        public_items = self.client.get("/api/gallery").get_json()["items"]
        self.assertEqual(public_items, [item])
        public_photo = self.client.get(item["imageUrl"])
        self.assertEqual(public_photo.status_code, 200)
        self.assertEqual(public_photo.mimetype, "image/png")
        self.assertEqual(public_photo.data, photo)
        self.assertEqual(
            self.client.get("/api/admin/gallery").get_json()["items"], [item]
        )

        updated_details = {
            **gallery_metadata,
            "eventName": "Annual Cytometry Symposium",
            "eventDate": "2026-09-14",
            "description": "Participants at the annual symposium",
        }
        unauthorized_update = self.client.put(
            f"/api/admin/gallery/{item['id']}",
            data=updated_details,
        )
        self.assertEqual(unauthorized_update.status_code, 401)
        updated = self.client.put(
            f"/api/admin/gallery/{item['id']}",
            data=updated_details,
            headers=self.admin_headers(),
        )
        self.assertEqual(updated.status_code, 200)
        updated_item = updated.get_json()["item"]
        self.assertEqual(updated_item["eventName"], updated_details["eventName"])
        self.assertEqual(updated_item["eventDate"], updated_details["eventDate"])
        self.assertEqual(updated_item["description"], updated_details["description"])
        self.assertEqual(
            self.client.get(updated_item["imageUrl"]).data, photo
        )

        replacement_photo = b"\xff\xd8\xffreplacement-gallery-photo"
        replaced = self.client.put(
            f"/api/admin/gallery/{item['id']}",
            data={
                **updated_details,
                "photo": (io.BytesIO(replacement_photo), "replacement.jpg"),
            },
            headers=self.admin_headers(),
        )
        self.assertEqual(replaced.status_code, 200)
        replaced_item = replaced.get_json()["item"]
        self.assertEqual(
            self.client.get(replaced_item["imageUrl"]).data, replacement_photo
        )
        self.assertEqual(self.client.get(item["imageUrl"]).status_code, 200)

        deleted = self.client.delete(
            f"/api/admin/gallery/{item['id']}",
            headers=self.admin_headers(),
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertIsNone(deleted.get_json()["warning"])
        self.assertEqual(self.client.get("/api/gallery").get_json(), {"items": []})
        self.assertEqual(self.client.get(replaced_item["imageUrl"]).status_code, 404)
        self.assertEqual(
            self.client.delete(
                f"/api/admin/gallery/{item['id']}",
                headers=self.admin_headers(),
            ).status_code,
            404,
        )

    def test_existing_gallery_rows_gain_event_name_and_date_columns(self):
        connection = sqlite3.connect(facility_app.BOOKING_DATABASE)
        try:
            connection.execute(
                """CREATE TABLE facility_gallery_items (
                    id TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """INSERT INTO facility_gallery_items
                   (id, description, image_path, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    "GL-EXISTING",
                    "Earlier workshop photo",
                    "gallery/GL-EXISTING/photo.png",
                    "2026-09-01T00:00:00+00:00",
                    "2026-09-01T00:00:00+00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        response = self.client.get("/api/gallery")
        self.assertEqual(response.status_code, 200)
        item = response.get_json()["items"][0]
        self.assertEqual(item["eventName"], "Event photo")
        self.assertIsNone(item["eventDate"])

    def test_existing_local_event_database_gains_workshop_image_column(self):
        connection = sqlite3.connect(facility_app.BOOKING_DATABASE)
        try:
            connection.execute(
                """CREATE TABLE facility_events (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    description TEXT NOT NULL,
                    link_label TEXT NOT NULL,
                    link_url TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            connection.commit()
        finally:
            connection.close()

        response = self.client.get("/api/events")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"events": []})
        archive = self.client.get("/api/workshops/archive")
        self.assertEqual(archive.status_code, 200)
        self.assertEqual(
            archive.get_json()["summary"],
            facility_app.ARCHIVED_WORKSHOP_SUMMARY,
        )

    def test_admin_login_rejects_incorrect_password(self):
        response = self.client.post("/api/admin/login", json={"password": "wrong"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.client.get("/api/admin/bookings").status_code, 401)

    def test_admin_login_rejects_cross_origin_requests(self):
        response = self.client.post(
            "/api/admin/login",
            json={"password": "test-admin-password"},
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.client.get("/api/admin/bookings").status_code,
            401,
        )

    def test_admin_mutations_require_csrf_token_and_same_origin(self):
        created = self.client.post("/api/bookings", data=self.booking_data())
        booking_id = created.get_json()["id"]
        self.sign_in()
        url = f"/api/admin/bookings/{booking_id}"
        no_token = self.client.patch(url, json={"status": "cancelled"})
        self.assertEqual(no_token.status_code, 401)

        wrong_origin = self.client.patch(
            url,
            json={"status": "cancelled"},
            headers={
                **self.admin_headers(),
                "Origin": "https://attacker.example",
            },
        )
        self.assertEqual(wrong_origin.status_code, 403)

        accepted = self.client.patch(
            url,
            json={"status": "cancelled"},
            headers=self.admin_headers(),
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.get_json()["booking"]["status"], "cancelled")

    def test_admin_page_entry_requires_a_new_login(self):
        login = self.sign_in()
        self.assertTrue(login.get_json()["csrfToken"])
        session_cookie = login.headers["Set-Cookie"]
        self.assertIn("HttpOnly", session_cookie)
        self.assertIn("SameSite=Strict", session_cookie)
        self.assertEqual(
            self.client.get("/api/admin/session").headers["Cache-Control"],
            "no-store",
        )
        self.assertEqual(
            self.client.get("/api/admin/session").get_json()["authenticated"],
            True,
        )

        page = self.client.get("/admin.html")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers["Cache-Control"], "no-store")
        page.close()
        session_status = self.client.get("/api/admin/session")
        self.assertFalse(session_status.get_json()["authenticated"])
        self.assertEqual(
            self.client.get("/api/admin/bookings").status_code,
            401,
        )

    def test_security_headers_are_present_and_cors_is_not_wildcarded(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(
            response.headers["Referrer-Policy"],
            "strict-origin-when-cross-origin",
        )
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

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
        events = [
            event for event in result.get_json()["events"]
            if event["source"] == "calendar"
        ]
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
