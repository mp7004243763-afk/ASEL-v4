"""One-time SQLite -> Neon migration helper.

Run from backend/ with DATABASE_URL set and DATABASE_PATH pointing at the
SQLite file. It copies existing rows without deleting the source database.
Rows already present in Neon are skipped by primary key.
"""
import os
import sqlite3
import sys

import psycopg
from psycopg.rows import dict_row

SQLITE_PATH = os.getenv("DATABASE_PATH", "asel.sqlite3")
DATABASE_URL = os.getenv("DATABASE_URL")
TABLES = {
    "messages": ("id", "user_id", "role", "content", "created_at"),
    "memories": ("id", "user_id", "content", "created_at"),
    "reminders": ("id", "user_id", "chat_id", "text", "due_at", "status", "created_at", "sent_at"),
    "calendar_events": ("id", "user_id", "title", "starts_at", "ends_at", "notes", "created_at"),
    "link_codes": ("code", "telegram_user_id", "expires_at"),
    "user_links": ("mobile_user_id", "telegram_user_id"),
}


def main():
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL is missing; no migration performed.")
    if not os.path.isfile(SQLITE_PATH):
        raise SystemExit(f"SQLite source not found at {SQLITE_PATH}; no migration performed.")

    source = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    totals = {}
    try:
        with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10) as target:
            for table, columns in TABLES.items():
                rows = source.execute(
                    f"SELECT {', '.join(columns)} FROM {table}"
                ).fetchall()
                if not rows:
                    totals[table] = 0
                    continue
                names = ", ".join(columns)
                placeholders = ", ".join(["%s"] * len(columns))
                sql = f"INSERT INTO {table} ({names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING"
                inserted = 0
                for row in rows:
                    cur = target.execute(sql, tuple(row[col] for col in columns))
                    inserted += cur.rowcount
                totals[table] = inserted

            for table in ("messages", "memories", "reminders", "calendar_events"):
                target.execute(
                    "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    "GREATEST(COALESCE((SELECT MAX(id) FROM " + table + "), 1), 1), "
                    "EXISTS(SELECT 1 FROM " + table + "))",
                    (table,),
                )
    finally:
        source.close()

    print("Migration completed. Inserted rows:")
    for table, count in totals.items():
        print(f"{table}: {count}")
    print("The SQLite source was not modified or deleted.")


if __name__ == "__main__":
    main()
