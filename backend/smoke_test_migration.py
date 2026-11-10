"""Exercise the one-time SQLite -> PostgreSQL migration against a disposable source DB."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

source = Path("/tmp/asel-migration-source.sqlite3")
if source.exists():
    source.unlink()

con = sqlite3.connect(source)
con.executescript("""
CREATE TABLE messages (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE memories (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, content TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE reminders (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, chat_id TEXT, text TEXT NOT NULL, due_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at DATETIME DEFAULT CURRENT_TIMESTAMP, sent_at TEXT);
CREATE TABLE calendar_events (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT, notes TEXT NOT NULL DEFAULT '', created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE link_codes (code TEXT PRIMARY KEY, telegram_user_id TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE user_links (mobile_user_id TEXT PRIMARY KEY, telegram_user_id TEXT NOT NULL UNIQUE);
INSERT INTO messages(id,user_id,role,content) VALUES (101,'migration-user','user','preserve this message');
INSERT INTO memories(id,user_id,content) VALUES (102,'migration-user','remember this');
INSERT INTO reminders(id,user_id,chat_id,text,due_at) VALUES (103,'migration-user','123456','test reminder','2099-01-01T00:00:00+00:00');
INSERT INTO calendar_events(id,user_id,title,starts_at) VALUES (104,'migration-user','test event','2099-01-02T00:00:00+00:00');
INSERT INTO link_codes(code,telegram_user_id,expires_at) VALUES ('migration-code','123456','2099-01-01T00:00:00+00:00');
INSERT INTO user_links(mobile_user_id,telegram_user_id) VALUES ('migration-mobile','123456');
""")
con.commit()
con.close()

env = os.environ.copy()
env["DATABASE_PATH"] = str(source)
subprocess.run([sys.executable, "migrate_sqlite_to_postgres.py"], check=True, env=env)

import psycopg
from psycopg.rows import dict_row

with psycopg.connect(env["DATABASE_URL"], row_factory=dict_row) as target:
    assert target.execute("SELECT content FROM messages WHERE id=101").fetchone()["content"] == "preserve this message"
    assert target.execute("SELECT content FROM memories WHERE id=102").fetchone()["content"] == "remember this"
    assert target.execute("SELECT text FROM reminders WHERE id=103").fetchone()["text"] == "test reminder"
    assert target.execute("SELECT title FROM calendar_events WHERE id=104").fetchone()["title"] == "test event"
    assert target.execute("SELECT telegram_user_id FROM link_codes WHERE code='migration-code'").fetchone()["telegram_user_id"] == "123456"
    assert target.execute("SELECT telegram_user_id FROM user_links WHERE mobile_user_id='migration-mobile'").fetchone()["telegram_user_id"] == "123456"

print("SQLite -> PostgreSQL migration smoke test passed.")
