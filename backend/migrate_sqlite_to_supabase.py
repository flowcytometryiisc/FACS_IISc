import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as facility_app


def migrate(source_database, source_uploads):
    if not facility_app.use_supabase_storage():
        raise RuntimeError("Set DATABASE_URL to the target Supabase PostgreSQL connection.")

    source = sqlite3.connect(f"file:{source_database.resolve()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    target = facility_app.booking_connection()
    imported = 0
    skipped = 0
    try:
        rows = source.execute("SELECT * FROM bookings ORDER BY created_at, id").fetchall()
        for row in rows:
            exists = target.execute(
                "SELECT id FROM bookings WHERE id = ?", (row["id"],)
            ).fetchone()
            if exists:
                skipped += 1
                continue

            source_form = Path(row["form_path"]).resolve()
            upload_root = source_uploads.resolve()
            if source_form.parent != upload_root or not source_form.is_file():
                raise FileNotFoundError(
                    f"Booking {row['id']} is missing its PDF in the configured uploads folder."
                )
            content = source_form.read_bytes()
            if len(content) > 10 * 1024 * 1024 or not content.startswith(b"%PDF-"):
                raise ValueError(f"Booking {row['id']} has an invalid or oversized PDF.")

            object_key = f"{row['id']}/{source_form.name}"
            facility_app.supabase_storage_request(
                "POST", object_key, content, "application/pdf", upsert=True
            )
            inserted = False
            try:
                target.execute(
                    """INSERT INTO bookings (
                        id, created_at, user_name, pi_name, phone, email, department,
                        specimen, notes, slots, status, form_name, form_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        row["id"],
                        row["created_at"],
                        row["user_name"],
                        row["pi_name"],
                        row["phone"],
                        row["email"],
                        row["department"],
                        row["specimen"],
                        row["notes"],
                        row["slots"] if isinstance(row["slots"], str) else json.dumps(row["slots"]),
                        row["status"],
                        row["form_name"],
                        object_key,
                    ),
                )
                target.commit()
                inserted = True
            finally:
                if not inserted:
                    target.rollback()
                    try:
                        facility_app.supabase_storage_request("DELETE", object_key)
                    except facility_app.SupabaseStorageError:
                        facility_app.app.logger.exception(
                            "Unable to remove a form after a failed migration insert"
                        )
            imported += 1
    finally:
        target.close()
        source.close()
    return imported, skipped


def main():
    parser = argparse.ArgumentParser(
        description="Copy existing local booking records and PDFs to Supabase."
    )
    parser.add_argument(
        "--source-db",
        type=Path,
        default=facility_app.BOOKING_DATABASE,
        help="SQLite database to migrate (default: backend/instance/bookings.sqlite3)",
    )
    parser.add_argument(
        "--source-uploads",
        type=Path,
        default=facility_app.BOOKING_UPLOADS,
        help="Folder containing existing booking PDFs.",
    )
    args = parser.parse_args()
    if not args.source_db.is_file():
        parser.error(f"SQLite database not found: {args.source_db}")
    imported, skipped = migrate(args.source_db, args.source_uploads)
    print(f"Migration complete: {imported} imported, {skipped} already present.")


if __name__ == "__main__":
    main()
