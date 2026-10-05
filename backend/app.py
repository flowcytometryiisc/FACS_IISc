import io
import hmac
import json
import os
import re
import secrets
import sqlite3
import smtplib
import ssl
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from html.parser import HTMLParser
from pathlib import Path, PureWindowsPath
from urllib.parse import quote, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Flask, has_request_context, jsonify, request, send_file, send_from_directory, session
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix

BASE = Path(__file__).resolve().parents[1]
CALENDAR_URL = "https://www.brownbearsw.com/cal/flow_cytometry"
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = (
    os.environ.get("BOOKING_COOKIE_SECURE", "").lower() == "true"
    or os.environ.get("APP_ENV", "").lower() == "production"
)
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=15)
app.config["SESSION_REFRESH_EACH_REQUEST"] = False
trusted_proxy_hops = int(os.environ.get("TRUSTED_PROXY_HOPS", "0"))
if trusted_proxy_hops < 0:
    raise RuntimeError("TRUSTED_PROXY_HOPS must be zero or a positive integer.")
if trusted_proxy_hops:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=trusted_proxy_hops,
        x_proto=trusted_proxy_hops,
        x_host=trusted_proxy_hops,
    )


@app.before_request
def protect_admin_mutations():
    if not request.path.startswith("/api/admin/") or request.method in {
        "GET", "HEAD", "OPTIONS",
    }:
        return None
    origin = request.headers.get("Origin", "")
    if (
        not origin
        or origin == "null"
        or origin.rstrip("/") != f"{request.scheme}://{request.host}".rstrip("/")
    ):
        return jsonify({"error": "Admin requests must come from this website."}), 403
    try:
        parsed_origin = urlsplit(origin)
    except ValueError:
        return jsonify({"error": "Admin requests must come from this website."}), 403
    if (
        parsed_origin.scheme not in {"http", "https"}
        or not parsed_origin.netloc
        or parsed_origin.path
        or parsed_origin.query
        or parsed_origin.fragment
    ):
        return jsonify({"error": "Admin requests must come from this website."}), 403
    if request.path == "/api/admin/login":
        return None
    expected_token = session.get("admin_csrf_token", "")
    supplied_token = request.headers.get("X-CSRF-Token", "")
    if (
        not session.get("booking_admin")
        or not expected_token
        or not supplied_token
        or not hmac.compare_digest(expected_token, supplied_token)
    ):
        return jsonify({"error": "The admin session expired. Sign in again."}), 401
    return None


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    if request.path.startswith("/api/admin/") or request.path == "/admin.html":
        response.headers["Cache-Control"] = "no-store"
    if request.is_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response

BOOKING_DATABASE = BASE / "backend" / "instance" / "bookings.sqlite3"
BOOKING_UPLOADS = BASE / "backend" / "instance" / "booking-forms"
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "booking-forms")
BOOKING_SLOTS = (
    "10:00-11:00",
    "11:00-12:00",
    "12:00-13:00",
    "14:00-15:00",
    "15:00-16:00",
    "16:00-17:00",
)
BOOKING_SLOTS_BY_TYPE = {
    "Analyzer": BOOKING_SLOTS,
    "Sorter": BOOKING_SLOTS,
}
SORTER_CLEANING_NEXT = {
    current: following
    for current, following in zip(BOOKING_SLOTS, BOOKING_SLOTS[1:])
    if current.split("-", 1)[1] == following.split("-", 1)[0]
}
MAX_CONCURRENT_INSTRUMENTS = 2
BOOKING_WEEKDAYS = {0, 1, 2, 3, 4}
SPECIMEN_TYPES = (
    "Cell suspension",
    "Primary cells",
    "Cell line",
    "Tissue-derived cells",
    "Other",
)
BROWN_BEAR_INSTRUMENT_CLASSES = {
    "c_CYTOFLEX": "CytoFLEX LX",
    "c_SYMPHONY": "Symphony A1",
    "c_ARIA": "FACSAria™ Fusion",
    "c_DISCOVER": "Discover S8 Spectral Flow Cytometer",
}


def facility_today():
    return facility_now().date()


def facility_now():
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def slot_has_started(slot, now=None):
    current = now or facility_now()
    slot_date = date.fromisoformat(slot["date"])
    start_time = slot["time"].split("-", 1)[0]
    return slot_date < current.date() or (
        slot_date == current.date() and start_time <= current.strftime("%H:%M")
    )


def booking_connection():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        try:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg.types.json import Jsonb
        except ImportError as error:
            raise BookingConfigurationError(
                "Install backend requirements to use the Supabase PostgreSQL database."
            ) from error
        if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
            raise BookingConfigurationError(
                "Supabase persistence requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
            )
        if not os.environ.get("FLASK_SECRET_KEY"):
            raise BookingConfigurationError(
                "Set a persistent FLASK_SECRET_KEY before connecting to Supabase."
            )
        try:
            connection = psycopg.connect(
                database_url,
                connect_timeout=10,
                row_factory=dict_row,
            )
        except psycopg.Error as error:
            raise BookingDatabaseError from error
        actor = "admin" if has_request_context() and session.get("booking_admin") else "public"
        return PostgresBookingConnection(connection, Jsonb, psycopg.Error, actor)

    if os.environ.get("APP_ENV", "").lower() == "production":
        raise BookingConfigurationError(
            "Set DATABASE_URL in production; SQLite is only for local development."
        )
    BOOKING_DATABASE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(BOOKING_DATABASE, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            user_name TEXT NOT NULL,
            pi_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT NOT NULL,
            department TEXT NOT NULL,
            specimen TEXT NOT NULL,
            notes TEXT NOT NULL,
            slots TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'cancelled')),
            form_name TEXT NOT NULL,
            form_path TEXT NOT NULL
        )
    """)
    schema_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'bookings'"
    ).fetchone()
    if schema_row and "'pending'" not in schema_row["sql"]:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("ALTER TABLE bookings RENAME TO bookings_before_review")
        connection.execute("""
            CREATE TABLE bookings (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                user_name TEXT NOT NULL,
                pi_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL,
                department TEXT NOT NULL,
                specimen TEXT NOT NULL,
                notes TEXT NOT NULL,
                slots TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'cancelled')),
                form_name TEXT NOT NULL,
                form_path TEXT NOT NULL
            )
        """)
        connection.execute("""
            INSERT INTO bookings (
                id, created_at, user_name, pi_name, phone, email,
                department, specimen, notes, slots, status, form_name, form_path
            )
            SELECT id, created_at, user_name, pi_name, phone, email,
                   department, specimen, notes, slots, status, form_name, form_path
            FROM bookings_before_review
        """)
        connection.execute("DROP TABLE bookings_before_review")
        connection.commit()
    return connection


class PostgresBookingConnection:
    def __init__(self, connection, jsonb_type, database_error_type, actor):
        self.connection = connection
        self.jsonb_type = jsonb_type
        self.database_error_type = database_error_type
        self.actor = actor

    def execute(self, statement, parameters=()):
        begins_transaction = "BEGIN IMMEDIATE" in statement
        statement = statement.replace("BEGIN IMMEDIATE", "BEGIN")
        values = list(parameters)
        if "INSERT INTO bookings" in statement and len(values) > 9:
            values[9] = self.jsonb_type(json.loads(values[9]))
        elif "UPDATE bookings SET" in statement and "slots = ?" in statement:
            slot_value_index = statement.split("slots = ?", 1)[0].count("?")
            values[slot_value_index] = self.jsonb_type(
                json.loads(values[slot_value_index])
            )
        try:
            cursor = self.connection.execute(statement.replace("?", "%s"), values)
            if begins_transaction:
                self.connection.execute(
                    "SELECT set_config('app.actor', %s, true)",
                    (self.actor,),
                )
                self.connection.execute(
                    "SELECT pg_advisory_xact_lock(9152026, 42)"
                )
            return cursor
        except self.database_error_type as error:
            if getattr(error, "sqlstate", None) == "23P01":
                raise BookingSlotConflict from error
            raise BookingDatabaseError from error

    def commit(self):
        try:
            self.connection.commit()
        except self.database_error_type as error:
            if getattr(error, "sqlstate", None) == "23P01":
                raise BookingSlotConflict from error
            raise BookingDatabaseError from error

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


class BookingSlotConflict(Exception):
    pass


class BookingConfigurationError(Exception):
    pass


class BookingDatabaseError(Exception):
    pass


class SupabaseStorageError(Exception):
    pass


def use_supabase_storage():
    return bool(os.environ.get("DATABASE_URL"))


def supabase_storage_request(method, object_key, content=None, content_type=None, upsert=False):
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not supabase_url or not service_key:
        raise SupabaseStorageError(
            "Supabase Storage requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
        )
    encoded_key = quote(object_key, safe="/")
    if method == "DELETE":
        endpoint = f"{supabase_url}/storage/v1/object/{quote(SUPABASE_STORAGE_BUCKET, safe='')}"
        body = json.dumps({"prefixes": [object_key]}).encode("utf-8")
        request_type = "application/json"
    else:
        endpoint = (
            f"{supabase_url}/storage/v1/object/"
            f"{quote(SUPABASE_STORAGE_BUCKET, safe='')}/{encoded_key}"
        )
        body = content
        request_type = content_type or "application/octet-stream"
    storage_request = Request(
        endpoint,
        data=body,
        method=method,
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": request_type,
            "x-upsert": "true" if upsert else "false",
        },
    )
    try:
        with urlopen(storage_request, timeout=20) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        app.logger.exception("Supabase Storage request failed")
        raise SupabaseStorageError(
            "The uploaded facility form could not be stored or retrieved."
        ) from error


def store_booking_form(object_key, content):
    if use_supabase_storage():
        supabase_storage_request("POST", object_key, content, "application/pdf")
        return object_key
    BOOKING_UPLOADS.mkdir(parents=True, exist_ok=True)
    local_path = BOOKING_UPLOADS / object_key
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        local_path.write_bytes(content)
    except OSError:
        if local_path.exists():
            local_path.unlink()
        raise
    return str(local_path)


def remove_booking_form(form_path):
    if not form_path:
        return True
    if use_supabase_storage():
        try:
            supabase_storage_request("DELETE", form_path)
        except SupabaseStorageError:
            return False
        return True
    local_path = Path(form_path).resolve()
    if not local_path.is_file():
        return True
    if local_path.parent != BOOKING_UPLOADS.resolve():
        app.logger.error("Refusing to delete a stored user form outside the upload directory")
        return False
    try:
        local_path.unlink()
    except OSError:
        app.logger.exception("Unable to remove the deleted booking's uploaded form")
        return False
    return True


def read_booking_form(form_path):
    if use_supabase_storage():
        return supabase_storage_request("GET", form_path)
    local_path = Path(form_path).resolve()
    if local_path.parent != BOOKING_UPLOADS.resolve() or not local_path.is_file():
        app.logger.error("Stored user form is missing or outside the upload directory")
        return None
    return local_path.read_bytes()


def slots_from_row(row):
    value = row["slots"]
    return json.loads(value) if isinstance(value, str) else value


def booking_row(row):
    instruments = {item["name"]: item for item in load_json("instruments.json")}
    instrument_colors = {
        instrument["name"]: instrument.get("color", "gray")
        for instrument in instruments.values()
    }
    slots = expand_stored_slots(slots_from_row(row), instruments)
    for slot in slots:
        slot.setdefault("color", instrument_colors.get(slot["instrument"], "gray"))
    is_uploaded_form = bool(row["form_path"]) and not row["form_path"].startswith(
        "admin-created:"
    )
    return {
        "id": row["id"],
        "createdAt": row["created_at"],
        "userName": row["user_name"],
        "piName": row["pi_name"],
        "phone": row["phone"],
        "email": row["email"],
        "department": row["department"],
        "specimen": row["specimen"],
        "notes": row["notes"],
        "slots": slots,
        "status": row["status"],
        "formName": row["form_name"],
        "hasForm": is_uploaded_form,
    }


def require_admin():
    if not session.get("booking_admin"):
        return jsonify({"error": "Admin sign-in is required."}), 401
    return None


def send_booking_email(recipient, subject, body):
    settings = {
        "host": os.environ.get("SMTP_HOST", "").strip(),
        "username": os.environ.get("SMTP_USERNAME", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "sender": os.environ.get("SMTP_FROM_EMAIL", "").strip(),
    }
    if any(not value for value in settings.values()):
        return {
            "sent": False,
            "error": "Email is not configured; set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, and SMTP_FROM_EMAIL.",
        }
    message = EmailMessage()
    message["From"] = settings["sender"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
        if os.environ.get("SMTP_USE_SSL", "").lower() == "true":
            with smtplib.SMTP_SSL(
                settings["host"], port, timeout=15,
                context=ssl.create_default_context(),
            ) as server:
                server.login(settings["username"], settings["password"])
                server.send_message(message)
        else:
            with smtplib.SMTP(settings["host"], port, timeout=15) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(settings["username"], settings["password"])
                server.send_message(message)
    except (OSError, smtplib.SMTPException, ValueError) as error:
        app.logger.exception("Booking notification email could not be sent")
        return {"sent": False, "error": f"Email delivery failed: {error}"}
    return {"sent": True, "error": None}


def notify_booking_request(booking):
    sessions = "\n".join(
        f"- {slot['instrument']}: {slot['date']} {slot['time']}"
        for slot in booking["slots"]
    )
    details = (
        f"Booking ID: {booking['id']}\n"
        f"User: {booking['userName']}\n"
        f"PI: {booking['piName']}\n"
        f"Email: {booking['email']}\n"
        f"Phone: {booking['phone']}\n"
        f"Specimen: {booking['specimen']}\n"
        f"Sessions:\n{sessions}\n"
    )
    admin_email = os.environ.get("ADMIN_NOTIFICATION_EMAIL", "").strip()
    admin_result = send_booking_email(
        admin_email,
        f"Booking request pending review · {booking['id']}",
        f"A new booking request is waiting for review.\n\n{details}",
    ) if admin_email else {
        "sent": False,
        "error": "Set ADMIN_NOTIFICATION_EMAIL to receive new-request alerts.",
    }
    user_result = send_booking_email(
        booking["email"],
        f"Booking request received · {booking['id']}",
        f"Hello {booking['userName']},\n\n"
        "Your request is being held while facility staff review it. "
        "We will email you after a decision.\n\n"
        f"{details}",
    )
    for recipient_type, result in (("facility", admin_result), ("user", user_result)):
        if not result["sent"]:
            app.logger.error(
                "Booking %s %s notification was not delivered: %s",
                booking["id"], recipient_type, result["error"],
            )
    return {"admin": admin_result, "user": user_result}


def notify_booking_accepted(booking):
    sessions = "\n".join(
        f"- {slot['instrument']}: {slot['date']} {slot['time']}"
        for slot in booking["slots"]
    )
    result = send_booking_email(
        booking["email"],
        f"Booking accepted · {booking['id']}",
        f"Hello {booking['userName']},\n\n"
        f"Your facility booking request {booking['id']} has been accepted.\n\n"
        f"Sessions:\n{sessions}\n",
    )
    if not result["sent"]:
        app.logger.error(
            "Booking %s acceptance notification was not delivered: %s",
            booking["id"], result["error"],
        )
    return result


class BrownBearCalendarError(Exception):
    pass


def fetch_brown_bear_month(month):
    url = f"{CALENDAR_URL}?Date={month}-01;Op=ShowIt"
    feed_request = Request(
        url,
        headers={
            "Accept": "text/html",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/128 Safari/537.36"
            ),
        },
    )
    try:
        with urlopen(feed_request, timeout=12) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(charset, errors="replace")
    except (HTTPError, URLError, TimeoutError, OSError) as error:
        app.logger.exception("Unable to retrieve the Brown Bear calendar")
        raise BrownBearCalendarError(
            "The live Brown Bear calendar could not be reached. Please try again."
        ) from error

    parser = BrownBearCalendarParser()
    parser.feed(html)
    if not parser.header_cells or not parser.day_row_count:
        app.logger.error("Brown Bear response did not contain a monthly calendar")
        raise BrownBearCalendarError(
            "Brown Bear did not return the requested monthly calendar."
        )
    instrument_colors = {
        instrument["name"]: instrument.get("color", "gray")
        for instrument in load_json("instruments.json")
    }
    return [
        {**event, "color": instrument_colors.get(event["instrument"], "neutral")}
        for event in parser.events
    ]


def brown_bear_events_between(start_date, end_date):
    events = []
    month = start_date.replace(day=1)
    final_month = end_date.replace(day=1)
    while month <= final_month:
        month_key = month.strftime("%Y-%m")
        events.extend(
            event for event in fetch_brown_bear_month(month_key)
            if start_date.isoformat() <= event["date"] <= end_date.isoformat()
        )
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return events


def event_time_range(time_text):
    parts = re.split(r"\s*[-\u2012-\u2015\u2212]\s*", time_text.strip(), maxsplit=1)
    if len(parts) != 2:
        return None

    def parse_time(value):
        match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*([AP]M)?", value.strip(), re.IGNORECASE)
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2) or "0")
        marker = (match.group(3) or "").upper()
        if minute > 59 or hour > (12 if marker else 23) or hour < (1 if marker else 0):
            return None
        if marker:
            hour %= 12
            if marker == "PM":
                hour += 12
        return hour * 60 + minute, marker

    start = parse_time(parts[0])
    end = parse_time(parts[1])
    if start is None or end is None:
        return None
    start_minutes, start_marker = start
    end_minutes, end_marker = end
    if start_marker and not end_marker and end_minutes < start_minutes:
        end_minutes += 12 * 60
    if end_minutes <= start_minutes:
        return None
    return start_minutes, end_minutes


def expand_stored_slots(slots, instruments):
    expanded = {}
    for slot in slots:
        if slot["time"] in BOOKING_SLOTS:
            times = (slot["time"],)
        else:
            time_range = event_time_range(slot["time"])
            if time_range is None:
                continue
            start, end = time_range
            times = tuple(
                time for time in BOOKING_SLOTS
                if int(time[:2]) * 60 + int(time[3:5]) < end
                and start < int(time[6:8]) * 60 + int(time[9:11])
            )
        for time in times:
            instrument = instruments.get(slot["instrument"])
            if instrument is None or time not in BOOKING_SLOTS_BY_TYPE.get(
                instrument.get("type"), ()
            ):
                continue
            expanded[(slot["instrument"], slot["date"], time)] = {
                **slot,
                "time": time,
                "color": slot.get("color", instrument.get("color", "gray")),
            }
    return list(expanded.values())


def slot_identity(slot):
    return slot["instrument"], slot["date"], slot["time"]


def sorter_cleaning_slots(slots, instruments):
    occupied = {slot_identity(slot) for slot in slots}
    cleaning = set()
    for slot in slots:
        instrument = instruments.get(slot["instrument"])
        next_time = SORTER_CLEANING_NEXT.get(slot["time"])
        if (
            instrument
            and instrument.get("type") == "Sorter"
            and next_time
            and (slot["instrument"], slot["date"], next_time) not in occupied
        ):
            cleaning.add((slot["instrument"], slot["date"], next_time))
    return cleaning


def booking_conflict(candidate_slots, occupied_slots, instruments):
    candidate_keys = {slot_identity(slot) for slot in candidate_slots}
    occupied_keys = {slot_identity(slot) for slot in occupied_slots}
    if candidate_keys & occupied_keys:
        return "One or more selected sessions are already booked. Refresh availability."

    occupied_cleaning = sorter_cleaning_slots(occupied_slots, instruments)
    if candidate_keys & occupied_cleaning:
        return "That sorter slot is blocked for cleaning after the preceding session."
    candidate_cleaning = sorter_cleaning_slots(candidate_slots, instruments)
    if candidate_cleaning & (occupied_keys | candidate_keys):
        return "A selected sorter session would overlap a booked slot needed for cleaning."

    instruments_per_slot = {}
    for instrument, slot_date, time in occupied_keys | candidate_keys:
        instruments_per_slot.setdefault((slot_date, time), set()).add(instrument)
    if any(
        len(instrument_names) > MAX_CONCURRENT_INSTRUMENTS
        for instrument_names in instruments_per_slot.values()
    ):
        return "Only two instruments can be booked during the same time slot."
    return None


def validate_booking_fields(payload):
    fields = {
        "user_name": str(payload.get("userName", "")).strip(),
        "pi_name": str(payload.get("piName", "")).strip(),
        "phone": str(payload.get("phone", "")).strip(),
        "email": str(payload.get("email", "")).strip().lower(),
        "department": str(payload.get("department", "")).strip(),
        "specimen": str(payload.get("specimen", "")).strip(),
        "notes": str(payload.get("notes", "")).strip(),
    }
    required = ("user_name", "pi_name", "phone", "email", "specimen")
    if any(not fields[key] for key in required):
        return None, "Complete all required booking details."
    limits = {
        "user_name": 120, "pi_name": 120, "phone": 24, "email": 254,
        "department": 160, "specimen": 80, "notes": 1500,
    }
    if any(len(value) > limits[key] for key, value in fields.items()):
        return None, "One or more booking fields exceed the allowed length."
    digits = re.sub(r"\D", "", fields["phone"])
    if not 10 <= len(digits) <= 15:
        return None, "Enter a valid phone number with 10 to 15 digits."
    if parseaddr(fields["email"])[1] != fields["email"] or not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", fields["email"]
    ):
        return None, "Enter a valid email address."
    if fields["specimen"] not in SPECIMEN_TYPES:
        return None, "Select a valid specimen type."
    return fields, None


def normalize_booking_slots(slots, instrument_records):
    if not isinstance(slots, list) or not 1 <= len(slots) <= 12:
        return None, "Choose between 1 and 12 session slots."
    normalized = []
    seen = set()
    for slot in slots:
        if not isinstance(slot, dict):
            return None, "A selected session is invalid."
        instrument = slot.get("instrument")
        slot_date = slot.get("date")
        time = slot.get("time")
        try:
            parsed_date = date.fromisoformat(slot_date)
        except (TypeError, ValueError):
            return None, "A selected session has an invalid date."
        if (
            instrument not in instrument_records
            or time not in BOOKING_SLOTS_BY_TYPE.get(
                instrument_records[instrument]["type"], ()
            )
            or parsed_date.weekday() not in BOOKING_WEEKDAYS
            or parsed_date < facility_today()
            or parsed_date > facility_today() + timedelta(days=90)
        ):
            return None, "A selected session is no longer available."
        value = {
            "instrument": instrument,
            "date": slot_date,
            "time": time,
            "color": instrument_records[instrument].get("color", "gray"),
        }
        if slot_has_started(value):
            return None, "A selected session has already started."
        key = slot_identity(value)
        if key in seen:
            return None, "Remove duplicate session slots before saving."
        seen.add(key)
        normalized.append(value)
    return normalized, None


def brown_bear_booked_slots(events, instruments):
    instrument_records = {item["name"]: item for item in instruments}
    booked_slots = []
    for event in events:
        event_range = event_time_range(event.get("time", ""))
        if event_range is None:
            event_range = (0, 24 * 60)
        event_start, event_end = event_range
        instrument_name = event.get("instrument", "")
        if instrument_name in instrument_records:
            affected_instruments = [instrument_records[instrument_name]]
        else:
            affected_instruments = list(instruments)
        for slot_time in BOOKING_SLOTS:
            slot_start, slot_end = (
                int(part[:2]) * 60 + int(part[3:])
                for part in slot_time.split("-")
            )
            if slot_start >= event_end or event_start >= slot_end:
                continue
            for instrument in affected_instruments:
                booked_slots.append({
                    "instrument": instrument["name"],
                    "date": event["date"],
                    "time": slot_time,
                    "color": instrument.get("color", "gray"),
                    "source": "calendar",
                    "title": event.get("title", "Facility calendar booking"),
                })
    return booked_slots


@app.errorhandler(413)
def booking_upload_too_large(_error):
    return jsonify({"error": "The uploaded user form must be smaller than 10 MB."}), 413


@app.errorhandler(BookingConfigurationError)
def booking_persistence_not_configured(error):
    app.logger.error("Booking persistence is not configured: %s", error)
    return jsonify({"error": "The facility booking service is temporarily unavailable."}), 503


@app.errorhandler(BookingDatabaseError)
def booking_database_unavailable(_error):
    app.logger.exception("The facility booking database is unavailable")
    return jsonify({"error": "The facility booking service is temporarily unavailable."}), 503


@app.get("/api/booking-availability")
def get_booking_availability():
    start = request.args.get("start", "")
    end = request.args.get("end", "")
    try:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)
    except ValueError:
        return jsonify({"error": "Provide a valid start and end date as YYYY-MM-DD."}), 400
    if end_date < start_date or (end_date - start_date).days > 31:
        return jsonify({"error": "The requested date range must be within 31 days."}), 400

    try:
        brown_bear_events = brown_bear_events_between(start_date, end_date)
    except BrownBearCalendarError as error:
        return jsonify({"error": str(error)}), 502

    instruments = load_json("instruments.json")
    booked_slots = brown_bear_booked_slots(brown_bear_events, instruments)
    connection = booking_connection()
    try:
        rows = connection.execute(
            "SELECT slots, status FROM bookings WHERE status IN ('pending', 'confirmed')"
        ).fetchall()
    finally:
        connection.close()

    unavailable_slots = []
    unavailable_by_key = {}
    now = facility_now()
    instrument_records = {item["name"]: item for item in instruments}
    for row in rows:
        for slot in expand_stored_slots(slots_from_row(row), instrument_records):
            if start <= slot["date"] <= end:
                booked_slots.append({
                    **slot,
                    "color": slot.get(
                        "color",
                        next(
                            (item.get("color", "gray") for item in instruments
                             if item["name"] == slot["instrument"]),
                            "gray",
                        ),
                    ),
                    "source": "portal",
                    "title": (
                        "Portal booking · Under review"
                        if row["status"] == "pending" else "Portal booking"
                    ),
                    "status": row["status"],
                })
    cleaning_slots = sorter_cleaning_slots(booked_slots, instrument_records)
    for instrument_name, slot_date, time in cleaning_slots:
        instrument = next(item for item in instruments if item["name"] == instrument_name)
        booked_slots.append({
            "instrument": instrument_name,
            "date": slot_date,
            "time": time,
            "color": instrument.get("color", "gray"),
            "source": "cleaning",
            "title": "Blocked for cleaning",
        })

    occupied_by_time = {}
    for slot in booked_slots:
        if slot.get("source") != "cleaning":
            occupied_by_time.setdefault((slot["date"], slot["time"]), set()).add(
                slot["instrument"]
            )
    for (slot_date, time), instrument_names in occupied_by_time.items():
        if len(instrument_names) >= MAX_CONCURRENT_INSTRUMENTS:
            unavailable_by_key[(slot_date, time)] = "operator_limit"

    current = now.date().isoformat()
    for day_offset in range((end_date - start_date).days + 1):
        slot_date = (start_date + timedelta(days=day_offset)).isoformat()
        if slot_date != current:
            continue
        unavailable_by_key.update({
            (slot_date, time): "started"
            for time in BOOKING_SLOTS
            if time.split("-", 1)[0] <= now.strftime("%H:%M")
        })
    for day_offset in range((end_date - start_date).days + 1):
        slot_date = start_date + timedelta(days=day_offset)
        if slot_date.weekday() not in BOOKING_WEEKDAYS:
            unavailable_by_key.update({
                (slot_date.isoformat(), time): "weekend"
                for time in BOOKING_SLOTS
            })
    unavailable_slots.extend(
        {"date": slot_date, "time": time, "reason": reason}
        for (slot_date, time), reason in unavailable_by_key.items()
    )
    response = jsonify({
        "start": start,
        "end": end,
        "booked": booked_slots,
        "unavailable": unavailable_slots,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/bookings")
def create_booking():
    fields = {
        "user_name": request.form.get("userName", "").strip(),
        "pi_name": request.form.get("piName", "").strip(),
        "phone": request.form.get("phone", "").strip(),
        "email": request.form.get("email", "").strip().lower(),
        "department": request.form.get("department", "").strip(),
        "specimen": request.form.get("specimen", "").strip(),
        "notes": request.form.get("notes", "").strip(),
    }
    required = ("user_name", "pi_name", "phone", "email", "specimen")
    if any(not fields[key] for key in required):
        return jsonify({"error": "Complete all required booking details."}), 400
    limits = {
        "user_name": 120,
        "pi_name": 120,
        "phone": 24,
        "email": 254,
        "department": 160,
        "specimen": 80,
        "notes": 1500,
    }
    if any(len(value) > limits[key] for key, value in fields.items()):
        return jsonify({"error": "One or more booking fields exceed the allowed length."}), 400
    digits = re.sub(r"\D", "", fields["phone"])
    if not 10 <= len(digits) <= 15:
        return jsonify({"error": "Enter a valid phone number with 10 to 15 digits."}), 400
    if parseaddr(fields["email"])[1] != fields["email"] or not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", fields["email"]
    ):
        return jsonify({"error": "Enter a valid email address."}), 400
    if fields["specimen"] not in SPECIMEN_TYPES:
        return jsonify({"error": "Select a valid specimen type."}), 400

    try:
        slots = json.loads(request.form.get("slots", ""))
    except json.JSONDecodeError:
        return jsonify({"error": "Select at least one available session."}), 400
    instrument_records = {
        item["name"]: item for item in load_json("instruments.json")
    }
    instruments = set(instrument_records)
    if not isinstance(slots, list) or not 1 <= len(slots) <= 12:
        return jsonify({"error": "Select between 1 and 12 session slots."}), 400
    normalized_slots = []
    seen_slots = set()
    for slot in slots:
        if not isinstance(slot, dict):
            return jsonify({"error": "A selected session is invalid."}), 400
        instrument = slot.get("instrument")
        slot_date = slot.get("date")
        time = slot.get("time")
        try:
            parsed_date = date.fromisoformat(slot_date)
        except (TypeError, ValueError):
            return jsonify({"error": "A selected session has an invalid date."}), 400
        if (
            instrument not in instruments
            or time not in BOOKING_SLOTS_BY_TYPE.get(
                instrument_records[instrument]["type"], ()
            )
            or parsed_date.weekday() not in BOOKING_WEEKDAYS
            or parsed_date < facility_today()
            or parsed_date > facility_today() + timedelta(days=90)
        ):
            return jsonify({"error": "A selected session is no longer available."}), 400
        normalized = {
            "instrument": instrument,
            "date": slot_date,
            "time": time,
            "color": instrument_records[instrument].get("color", "gray"),
        }
        if slot_has_started(normalized):
            return jsonify({"error": "A selected session has already started. Choose a future time."}), 400
        slot_key = (instrument, slot_date, time)
        if slot_key in seen_slots:
            return jsonify({"error": "Remove duplicate session slots before booking."}), 400
        seen_slots.add(slot_key)
        normalized_slots.append(normalized)

    try:
        booking_start = min(date.fromisoformat(slot["date"]) for slot in normalized_slots)
        booking_end = max(date.fromisoformat(slot["date"]) for slot in normalized_slots)
        calendar_events = brown_bear_events_between(booking_start, booking_end)
    except BrownBearCalendarError as error:
        return jsonify({"error": str(error)}), 502
    calendar_booked = brown_bear_booked_slots(
        calendar_events, list(instrument_records.values())
    )
    if {
        slot_identity(slot) for slot in normalized_slots
    } & {slot_identity(slot) for slot in calendar_booked}:
        return jsonify({
            "error": "One or more selected sessions are already booked in the facility calendar. Refresh availability."
        }), 409
    conflict = booking_conflict(normalized_slots, calendar_booked, instrument_records)
    if conflict:
        return jsonify({"error": conflict}), 409

    upload = request.files.get("userForm")
    if upload is None or not upload.filename:
        return jsonify({"error": "Attach the completed facility user form as a PDF."}), 400
    original_name = secure_filename(PureWindowsPath(upload.filename).name)
    if not original_name.lower().endswith(".pdf"):
        return jsonify({"error": "The facility user form must be a PDF."}), 400
    content = upload.stream.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        return jsonify({"error": "The uploaded user form must be smaller than 10 MB."}), 413
    if not content.startswith(b"%PDF-"):
        return jsonify({"error": "The uploaded file is not a valid PDF document."}), 400

    booking_id = f"FC-{facility_today():%y%m%d}-{secrets.token_hex(3).upper()}"
    stored_form = f"{secrets.token_hex(16)}.pdf"
    storage_key = f"{booking_id}/{stored_form}" if use_supabase_storage() else stored_form
    form_path = ""
    connection = None
    try:
        connection = booking_connection()
        form_path = store_booking_form(storage_key, content)
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT slots, status FROM bookings WHERE status IN ('pending', 'confirmed')"
        ).fetchall()
        occupied = [
            slot
            for row in existing
            for slot in expand_stored_slots(slots_from_row(row), instrument_records)
        ]
        conflict = booking_conflict(
            normalized_slots, calendar_booked + occupied, instrument_records
        )
        if conflict:
            connection.rollback()
            remove_booking_form(form_path)
            return jsonify({"error": conflict}), 409

        connection.execute(
            """INSERT INTO bookings (
                id, created_at, user_name, pi_name, phone, email, department,
                specimen, notes, slots, status, form_name, form_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (
                booking_id,
                datetime.now(timezone.utc).isoformat(),
                fields["user_name"],
                fields["pi_name"],
                fields["phone"],
                fields["email"],
                fields["department"],
                fields["specimen"],
                fields["notes"],
                json.dumps(normalized_slots),
                original_name,
                str(form_path),
            ),
        )
        connection.commit()
    except (sqlite3.IntegrityError, BookingSlotConflict):
        if connection:
            connection.rollback()
        remove_booking_form(form_path)
        return jsonify({"error": "One or more selected slots were just booked. Refresh availability."}), 409
    except SupabaseStorageError as error:
        if connection:
            connection.rollback()
        remove_booking_form(form_path)
        return jsonify({"error": str(error)}), 502
    except BookingConfigurationError as error:
        if connection:
            connection.rollback()
        remove_booking_form(form_path)
        return jsonify({"error": str(error)}), 503
    except OSError:
        if connection:
            connection.rollback()
        remove_booking_form(form_path)
        app.logger.exception("Unable to save the facility user form")
        return jsonify({"error": "The booking could not be saved. Please try again."}), 500
    except (sqlite3.Error, BookingDatabaseError):
        if connection:
            connection.rollback()
        remove_booking_form(form_path)
        app.logger.exception("Unable to save the facility booking")
        return jsonify({"error": "The booking could not be saved. Please try again."}), 500
    finally:
        if connection:
            connection.close()

    booking = {
        "id": booking_id,
        "userName": fields["user_name"],
        "piName": fields["pi_name"],
        "email": fields["email"],
        "phone": fields["phone"],
        "specimen": fields["specimen"],
        "slots": normalized_slots,
    }
    notifications = notify_booking_request(booking)
    return jsonify({
        "id": booking_id,
        "status": "pending",
        "slots": normalized_slots,
        "notifications": notifications,
    }), 201


@app.get("/api/admin/session")
def get_admin_session():
    authenticated = bool(session.get("booking_admin"))
    response = jsonify({
        "authenticated": authenticated,
        "csrfToken": session.get("admin_csrf_token") if authenticated else None,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/admin/login")
def admin_login():
    password = os.environ.get("BOOKING_ADMIN_PASSWORD", "")
    if not password:
        return jsonify({"error": "Admin access is not configured. Set BOOKING_ADMIN_PASSWORD on the server."}), 503
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Submit the admin password as a JSON object."}), 400
    submitted = payload.get("password", "")
    if not isinstance(submitted, str) or not hmac.compare_digest(submitted, password):
        return jsonify({"error": "The password is incorrect."}), 401
    session.clear()
    session.permanent = True
    session["booking_admin"] = True
    session["admin_csrf_token"] = secrets.token_urlsafe(32)
    return jsonify({
        "authenticated": True,
        "csrfToken": session["admin_csrf_token"],
    })


@app.post("/api/admin/logout")
def admin_logout():
    session.clear()
    return jsonify({"authenticated": False})


@app.get("/api/admin/bookings")
def get_admin_bookings():
    denied = require_admin()
    if denied:
        return denied
    connection = booking_connection()
    try:
        rows = connection.execute(
            "SELECT * FROM bookings ORDER BY created_at DESC"
        ).fetchall()
    finally:
        connection.close()
    response = jsonify({"bookings": [booking_row(row) for row in rows]})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/admin/calendar")
def get_admin_calendar():
    denied = require_admin()
    if denied:
        return denied
    month = request.args.get("month", "")
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        return jsonify({"error": "Provide the calendar month as YYYY-MM."}), 400
    try:
        datetime.strptime(f"{month}-01", "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "The requested calendar month is invalid."}), 400
    try:
        events = [
            {**event, "source": "calendar"}
            for event in fetch_brown_bear_month(month)
            if event["date"].startswith(month)
        ]
    except BrownBearCalendarError as error:
        return jsonify({"error": str(error)}), 502

    connection = booking_connection()
    try:
        rows = connection.execute(
            "SELECT id, user_name, slots, status FROM bookings WHERE status IN ('pending', 'confirmed')"
        ).fetchall()
    finally:
        connection.close()
    instrument_colors = {
        item["name"]: item.get("color", "gray") for item in load_json("instruments.json")
    }
    instrument_records = {item["name"]: item for item in load_json("instruments.json")}
    for row in rows:
        for slot in expand_stored_slots(slots_from_row(row), instrument_records):
            if slot["date"].startswith(month):
                events.append({
                    "date": slot["date"],
                    "time": slot["time"],
                    "title": (
                        f"{row['user_name']} · Under review"
                        if row["status"] == "pending" else row["user_name"]
                    ),
                    "instrument": slot["instrument"],
                    "color": slot.get(
                        "color", instrument_colors.get(slot["instrument"], "gray")
                    ),
                    "source": "portal",
                    "bookingId": row["id"],
                })
    events.sort(key=lambda event: (event["date"], event["time"], event["instrument"]))
    response = jsonify({
        "month": month,
        "timezone": "Asia/Kolkata",
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "events": events,
        "brownBearAdminUrl": f"{CALENDAR_URL}?Op=AdminPage",
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@app.patch("/api/admin/bookings/<booking_id>")
def update_admin_booking(booking_id):
    denied = require_admin()
    if denied:
        return denied
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Submit the booking status as a JSON object."}), 400
    status = payload.get("status")
    if status not in ("pending", "confirmed", "cancelled"):
        return jsonify({"error": "Choose pending, confirmed, or cancelled as the booking status."}), 400

    connection = booking_connection()
    try:
        row = connection.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        if row is None:
            return jsonify({"error": "Booking not found."}), 404
        initial_status = row["status"]
        instrument_records = {
            item["name"]: item for item in load_json("instruments.json")
        }
        calendar_booked = []
        needs_availability_check = (
            status in ("pending", "confirmed") and row["status"] == "cancelled"
        ) or (status == "confirmed" and row["status"] == "pending")
        if needs_availability_check:
            restoring_slots = expand_stored_slots(
                slots_from_row(row), instrument_records
            )
            if any(slot_has_started(item) for item in restoring_slots):
                return jsonify({"error": "A past session cannot be restored."}), 409
            try:
                calendar_events = brown_bear_events_between(
                    min(date.fromisoformat(item["date"]) for item in restoring_slots),
                    max(date.fromisoformat(item["date"]) for item in restoring_slots),
                )
            except BrownBearCalendarError as error:
                return jsonify({"error": str(error)}), 502
            calendar_booked = brown_bear_booked_slots(
                calendar_events, list(instrument_records.values())
            )
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        if row is None:
            connection.rollback()
            return jsonify({"error": "Booking not found."}), 404
        if row["status"] != initial_status:
            connection.rollback()
            return jsonify({"error": "The booking status changed. Refresh the admin booking list."}), 409
        needs_availability_check = (
            status in ("pending", "confirmed") and row["status"] == "cancelled"
        ) or (status == "confirmed" and row["status"] == "pending")
        if needs_availability_check:
            restoring_slots = expand_stored_slots(
                slots_from_row(row), instrument_records
            )
            if any(slot_has_started(item) for item in restoring_slots):
                connection.rollback()
                return jsonify({"error": "A past session cannot be restored."}), 409
            existing = connection.execute(
                "SELECT id, slots FROM bookings WHERE status IN ('pending', 'confirmed') AND id != ?",
                (booking_id,),
            ).fetchall()
            occupied = [
                item
                for other in existing
                for item in expand_stored_slots(
                    slots_from_row(other), instrument_records
                )
            ]
            if {
                slot_identity(slot) for slot in restoring_slots
            } & {slot_identity(slot) for slot in calendar_booked}:
                connection.rollback()
                return jsonify({
                    "error": "The session is now booked in the facility calendar and cannot be restored."
                }), 409
            conflict = booking_conflict(
                restoring_slots, calendar_booked + occupied, instrument_records
            )
            if conflict:
                connection.rollback()
                return jsonify({"error": conflict}), 409
        connection.execute(
            "UPDATE bookings SET status = ? WHERE id = ?", (status, booking_id)
        )
        updated = connection.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        connection.commit()
    except BookingSlotConflict:
        connection.rollback()
        return jsonify({"error": "The session is already reserved by another booking."}), 409
    finally:
        connection.close()
    notification = None
    if status == "confirmed" and initial_status != "confirmed":
        notification = notify_booking_accepted(booking_row(updated))
    response = jsonify({
        "booking": booking_row(updated),
        "notification": notification,
    })
    response.headers["Cache-Control"] = "no-store"
    return response


def admin_booking_payload(payload):
    fields, error = validate_booking_fields(payload)
    if error:
        return None, None, error
    slots, error = normalize_booking_slots(
        payload.get("slots"),
        {item["name"]: item for item in load_json("instruments.json")},
    )
    if error:
        return None, None, error
    return fields, slots, None


def get_calendar_conflicts(slots, instruments):
    try:
        events = brown_bear_events_between(
            min(date.fromisoformat(slot["date"]) for slot in slots),
            max(date.fromisoformat(slot["date"]) for slot in slots),
        )
    except BrownBearCalendarError as error:
        return None, None, str(error)
    booked = brown_bear_booked_slots(events, list(instruments.values()))
    if {slot_identity(slot) for slot in slots} & {
        slot_identity(slot) for slot in booked
    }:
        return booked, "A selected session conflicts with the Brown Bear calendar.", None
    conflict = booking_conflict(slots, booked, instruments)
    return booked, conflict, None


@app.post("/api/admin/bookings")
def create_admin_booking():
    denied = require_admin()
    if denied:
        return denied
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Submit the booking details as a JSON object."}), 400
    fields, slots, error = admin_booking_payload(payload)
    if error:
        return jsonify({"error": error}), 400
    instruments = {item["name"]: item for item in load_json("instruments.json")}
    calendar_booked, error, calendar_error = get_calendar_conflicts(slots, instruments)
    if calendar_error:
        return jsonify({"error": calendar_error}), 502
    if error:
        return jsonify({"error": error}), 409

    booking_id = f"FC-{facility_today():%y%m%d}-{secrets.token_hex(3).upper()}"
    created_at = datetime.now(timezone.utc).isoformat()
    form_path = f"admin-created:{booking_id}"
    try:
        connection = booking_connection()
    except BookingConfigurationError as error:
        return jsonify({"error": str(error)}), 503
    except (sqlite3.Error, BookingDatabaseError):
        app.logger.exception("Unable to connect to the booking database")
        return jsonify({"error": "The booking database is temporarily unavailable."}), 503
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT slots FROM bookings WHERE status IN ('pending', 'confirmed')"
        ).fetchall()
        occupied = [
            slot
            for row in existing
            for slot in expand_stored_slots(slots_from_row(row), instruments)
        ]
        conflict = booking_conflict(slots, calendar_booked + occupied, instruments)
        if conflict:
            connection.rollback()
            return jsonify({"error": conflict}), 409
        connection.execute(
            """INSERT INTO bookings (
                id, created_at, user_name, pi_name, phone, email, department,
                specimen, notes, slots, status, form_name, form_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?, ?)""",
            (
                booking_id, created_at, fields["user_name"], fields["pi_name"],
                fields["phone"], fields["email"], fields["department"],
                fields["specimen"], fields["notes"], json.dumps(slots),
                "Added by facility staff", form_path,
            ),
        )
        connection.commit()
        created = connection.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
    except (sqlite3.IntegrityError, BookingSlotConflict):
        connection.rollback()
        return jsonify({"error": "One or more selected slots were just booked. Refresh availability."}), 409
    except (sqlite3.Error, BookingDatabaseError):
        connection.rollback()
        app.logger.exception("Unable to create the staff booking")
        return jsonify({"error": "The staff booking could not be saved."}), 500
    finally:
        connection.close()
    booking = booking_row(created)
    return jsonify({
        "booking": booking,
        "notification": notify_booking_accepted(booking),
    }), 201


@app.put("/api/admin/bookings/<booking_id>")
def edit_admin_booking(booking_id):
    denied = require_admin()
    if denied:
        return denied
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Submit the booking details as a JSON object."}), 400
    fields, slots, error = admin_booking_payload(payload)
    if error:
        return jsonify({"error": error}), 400
    instruments = {item["name"]: item for item in load_json("instruments.json")}
    calendar_booked, error, calendar_error = get_calendar_conflicts(slots, instruments)
    if calendar_error:
        return jsonify({"error": calendar_error}), 502
    if error:
        return jsonify({"error": error}), 409
    try:
        connection = booking_connection()
    except BookingConfigurationError as error:
        return jsonify({"error": str(error)}), 503
    except (sqlite3.Error, BookingDatabaseError):
        app.logger.exception("Unable to connect to the booking database")
        return jsonify({"error": "The booking database is temporarily unavailable."}), 503
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        if current is None:
            connection.rollback()
            return jsonify({"error": "Booking not found."}), 404
        if current["status"] in ("pending", "confirmed"):
            existing = connection.execute(
                "SELECT id, slots FROM bookings WHERE status IN ('pending', 'confirmed') AND id != ?",
                (booking_id,),
            ).fetchall()
            occupied = [
                slot
                for row in existing
                for slot in expand_stored_slots(slots_from_row(row), instruments)
            ]
            conflict = booking_conflict(slots, calendar_booked + occupied, instruments)
            if conflict:
                connection.rollback()
                return jsonify({"error": conflict}), 409
        connection.execute(
            """UPDATE bookings SET user_name = ?, pi_name = ?, phone = ?, email = ?,
                department = ?, specimen = ?, notes = ?, slots = ? WHERE id = ?""",
            (
                fields["user_name"], fields["pi_name"], fields["phone"],
                fields["email"], fields["department"], fields["specimen"],
                fields["notes"], json.dumps(slots), booking_id,
            ),
        )
        updated = connection.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        connection.commit()
    except (sqlite3.IntegrityError, BookingSlotConflict):
        connection.rollback()
        return jsonify({"error": "One or more selected slots were just booked. Refresh availability."}), 409
    except (sqlite3.Error, BookingDatabaseError):
        connection.rollback()
        app.logger.exception("Unable to update the staff booking")
        return jsonify({"error": "The booking could not be updated."}), 500
    finally:
        connection.close()
    return jsonify({"booking": booking_row(updated)})


@app.put("/api/admin/bookings/<booking_id>/slots")
def update_admin_booking_slots(booking_id):
    denied = require_admin()
    if denied:
        return denied
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("slots"), list):
        return jsonify({"error": "Submit the replacement sessions as a JSON array."}), 400
    slots = payload["slots"]
    if not 1 <= len(slots) <= 12:
        return jsonify({"error": "Choose between 1 and 12 session slots."}), 400

    instrument_records = {item["name"]: item for item in load_json("instruments.json")}
    normalized_slots = []
    seen_slots = set()
    for slot in slots:
        if not isinstance(slot, dict):
            return jsonify({"error": "A selected session is invalid."}), 400
        instrument = slot.get("instrument")
        slot_date = slot.get("date")
        time = slot.get("time")
        try:
            parsed_date = date.fromisoformat(slot_date)
        except (TypeError, ValueError):
            return jsonify({"error": "A selected session has an invalid date."}), 400
        if (
            instrument not in instrument_records
            or time not in BOOKING_SLOTS_BY_TYPE.get(
                instrument_records[instrument]["type"], ()
            )
            or parsed_date.weekday() not in BOOKING_WEEKDAYS
            or parsed_date < facility_today()
            or parsed_date > facility_today() + timedelta(days=90)
        ):
            return jsonify({"error": "A selected session is no longer available."}), 400
        normalized = {
            "instrument": instrument,
            "date": slot_date,
            "time": time,
            "color": instrument_records[instrument].get("color", "gray"),
        }
        if slot_has_started(normalized):
            return jsonify({"error": "A selected session has already started."}), 400
        key = (instrument, slot_date, time)
        if key in seen_slots:
            return jsonify({"error": "Remove duplicate session slots before saving."}), 400
        seen_slots.add(key)
        normalized_slots.append(normalized)

    try:
        calendar_events = brown_bear_events_between(
            min(date.fromisoformat(slot["date"]) for slot in normalized_slots),
            max(date.fromisoformat(slot["date"]) for slot in normalized_slots),
        )
    except BrownBearCalendarError as error:
        return jsonify({"error": str(error)}), 502
    calendar_booked = brown_bear_booked_slots(
        calendar_events, list(instrument_records.values())
    )
    if {
        slot_identity(slot) for slot in normalized_slots
    } & {slot_identity(slot) for slot in calendar_booked}:
        return jsonify({"error": "A replacement session conflicts with the Brown Bear calendar."}), 409
    conflict = booking_conflict(
        normalized_slots, calendar_booked, instrument_records
    )
    if conflict:
        return jsonify({"error": conflict}), 409

    connection = booking_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        if row is None:
            connection.rollback()
            return jsonify({"error": "Booking not found."}), 404
        if row["status"] not in ("pending", "confirmed"):
            connection.rollback()
            return jsonify({"error": "Only active bookings can be rescheduled."}), 409
        existing = connection.execute(
            "SELECT id, slots FROM bookings WHERE status IN ('pending', 'confirmed') AND id != ?",
            (booking_id,),
        ).fetchall()
        occupied = [
            slot
            for other in existing
            for slot in expand_stored_slots(
                slots_from_row(other), instrument_records
            )
        ]
        conflict = booking_conflict(
            normalized_slots, calendar_booked + occupied, instrument_records
        )
        if conflict:
            connection.rollback()
            return jsonify({"error": conflict}), 409
        connection.execute(
            "UPDATE bookings SET slots = ? WHERE id = ?",
            (json.dumps(normalized_slots), booking_id),
        )
        updated = connection.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        connection.commit()
    except BookingSlotConflict:
        connection.rollback()
        return jsonify({"error": "A replacement session is already reserved by another booking."}), 409
    finally:
        connection.close()
    response = jsonify({"booking": booking_row(updated)})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.delete("/api/admin/bookings/<booking_id>")
def delete_admin_booking(booking_id):
    denied = require_admin()
    if denied:
        return denied
    connection = booking_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT form_path FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
        if row is None:
            connection.rollback()
            return jsonify({"error": "Booking not found."}), 404
        form_path = row["form_path"]
        connection.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        connection.commit()
    finally:
        connection.close()

    form_deleted = (
        True
        if form_path.startswith("admin-created:")
        else remove_booking_form(form_path)
    )
    response = jsonify({"deleted": True, "formDeleted": form_deleted})
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/admin/bookings/<booking_id>/form")
def download_booking_form(booking_id):
    denied = require_admin()
    if denied:
        return denied
    connection = booking_connection()
    try:
        row = connection.execute(
            "SELECT form_name, form_path FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
    finally:
        connection.close()
    if row is None or not row["form_path"]:
        return jsonify({"error": "The booking form was not found."}), 404
    try:
        content = read_booking_form(row["form_path"])
    except SupabaseStorageError as error:
        return jsonify({"error": str(error)}), 502
    if content is None:
        return jsonify({"error": "The stored facility user form could not be found."}), 404
    response = send_file(
        io.BytesIO(content),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=secure_filename(row["form_name"]) or "facility-user-form.pdf",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


class BrownBearCalendarParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_calendar = False
        self.table_depth = 0
        self.row = None
        self.cell = None
        self.event = None
        self.capture = None
        self.header_cells = []
        self.day_row_count = 0
        self.events = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())

        if tag == "table":
            if not self.in_calendar and "CalBlock" in classes:
                self.in_calendar = True
                self.table_depth = 1
            elif self.in_calendar:
                self.table_depth += 1
            return

        if not self.in_calendar or self.table_depth != 1:
            return

        if tag == "tr":
            self.row = {"class": set(attributes.get("class", "").split()), "cells": []}
            return

        if tag in ("td", "th") and self.row is not None:
            self.cell = {
                "class": set(attributes.get("class", "").split()),
                "date": None,
                "events": [],
            }
            self.row["cells"].append(self.cell)
            return

        if self.cell is None:
            return

        if tag == "a" and "DayHeader" in self.cell["class"]:
            href = attributes.get("href", "")
            if "ShowDay" in href:
                match = re.search(r"Date=(\d{4})[-/](\d{2})[-/](\d{2})", href)
                if match:
                    self.cell["date"] = "-".join(match.groups())

        if tag == "div" and "CalEvent" in classes:
            category = next(
                (name for name in classes if name in BROWN_BEAR_INSTRUMENT_CLASSES),
                None,
            )
            self.event = {
                "time": "",
                "title": "",
                "instrument": (
                    BROWN_BEAR_INSTRUMENT_CLASSES[category] if category else ""
                ),
                "color": category.removeprefix("c_").lower() if category else "neutral",
            }
        elif tag == "div" and self.event is not None and "TimeLabel" in classes:
            self.capture = ("time", [])
        elif tag == "div" and self.event is not None and "EventLink" in classes:
            self.capture = ("title", [])

    def handle_data(self, data):
        if self.capture is not None:
            self.capture[1].append(data)

    def handle_endtag(self, tag):
        if not self.in_calendar:
            return

        if tag == "div" and self.capture is not None:
            field, parts = self.capture
            self.event[field] = " ".join(" ".join(parts).split())
            self.capture = None
            return

        if tag == "div" and self.event is not None and self.cell is not None:
            if self.event["title"]:
                self.cell["events"].append(self.event)
            self.event = None
            return

        if tag == "td":
            self.cell = None
            return

        if tag == "tr" and self.row is not None:
            if "DayHeaderRow" in self.row["class"]:
                self.header_cells = self.row["cells"]
            elif "DayRow" in self.row["class"]:
                self.day_row_count += 1
                for header, cell in zip(self.header_cells, self.row["cells"]):
                    date_value = header["date"]
                    if date_value:
                        self.events.extend(
                            {"date": date_value, **event}
                            for event in cell["events"]
                        )
            self.row = None
            return

        if tag == "table":
            self.table_depth -= 1
            if self.table_depth == 0:
                self.in_calendar = False


def load_json(name):
    path = BASE / "frontend" / "data" / name
    return json.loads(path.read_text(encoding="utf-8"))

@app.get("/api/health")
def health():
    try:
        connection = booking_connection()
        connection.close()
    except (BookingConfigurationError, BookingDatabaseError, sqlite3.Error):
        app.logger.exception("Booking database health check failed")
        return jsonify({"status": "unavailable", "service": "Flow Cytometry Facility API"}), 503
    return jsonify({
        "status": "ok",
        "service": "Flow Cytometry Facility API",
        "persistence": "supabase" if use_supabase_storage() else "sqlite",
    })

@app.get("/api/instruments")
def get_instruments():
    return jsonify(load_json("instruments.json"))

@app.get("/api/content")
def get_content():
    return jsonify(load_json("site-content.json"))


@app.get("/api/calendar")
def get_calendar():
    month = request.args.get("month", "")
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        return jsonify({"error": "Provide the calendar month as YYYY-MM."}), 400

    try:
        month_start = datetime.strptime(f"{month}-01", "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "The requested calendar month is invalid."}), 400

    try:
        events = [
            {**event, "source": "calendar"}
            for event in fetch_brown_bear_month(month)
            if event["date"].startswith(month)
        ]
    except BrownBearCalendarError as error:
        return jsonify({"error": str(error)}), 502

    portal_bookings_available = True
    try:
        connection = booking_connection()
        try:
            rows = connection.execute(
                "SELECT slots, status FROM bookings WHERE status IN ('pending', 'confirmed')"
            ).fetchall()
        finally:
            connection.close()
    except (BookingConfigurationError, BookingDatabaseError, sqlite3.Error):
        app.logger.exception("Unable to load portal bookings for the facility calendar")
        rows = []
        portal_bookings_available = False

    instrument_colors = {
        item["name"]: item.get("color", "gray") for item in load_json("instruments.json")
    }
    instrument_records = {item["name"]: item for item in load_json("instruments.json")}
    for row in rows:
        for slot in expand_stored_slots(slots_from_row(row), instrument_records):
            if slot["date"].startswith(month):
                events.append({
                    "date": slot["date"],
                    "time": slot["time"],
                    "title": (
                        "Portal booking · Under review"
                        if row["status"] == "pending" else "Portal booking"
                    ),
                    "instrument": slot["instrument"],
                    "color": slot.get("color", instrument_colors.get(slot["instrument"], "gray")),
                    "source": "portal",
                })
    result = jsonify({
        "month": month,
        "timezone": "Asia/Kolkata",
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "source": CALENDAR_URL,
        "events": events,
        "portalBookingsAvailable": portal_bookings_available,
        "portalBookingsWarning": (
            None if portal_bookings_available
            else "Website bookings are temporarily unavailable; only Brown Bear events are shown."
        ),
    })
    result.headers["Cache-Control"] = "no-store"
    return result


@app.get("/")
def serve_home():
    return send_from_directory(BASE / "frontend", "index.html")


@app.get("/<path:asset_path>")
def serve_frontend(asset_path):
    if asset_path == "admin.html":
        session.clear()
    return send_from_directory(BASE / "frontend", asset_path)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
