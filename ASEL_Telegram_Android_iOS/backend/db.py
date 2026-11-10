import sqlite3
from contextlib import contextmanager
from config import DATABASE_PATH

@contextmanager
def connect():
    con = sqlite3.connect(DATABASE_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        yield con
        con.commit()
    finally:
        con.close()

def init_db():
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            role TEXT NOT NULL, content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id)")
        con.execute("""CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            content TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id, id)")
        con.execute("""CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            chat_id TEXT, text TEXT NOT NULL, due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, sent_at TEXT)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, due_at)")
        con.execute("""CREATE TABLE IF NOT EXISTS calendar_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
            title TEXT NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT,
            notes TEXT NOT NULL DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_user_date ON calendar_events(user_id, starts_at)")
        con.execute("""CREATE TABLE IF NOT EXISTS link_codes (
            code TEXT PRIMARY KEY, telegram_user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL)""")
        con.execute("""CREATE TABLE IF NOT EXISTS user_links (
            mobile_user_id TEXT PRIMARY KEY, telegram_user_id TEXT NOT NULL UNIQUE)""")

def get_history(user_id, limit=20):
    uid = canonical_user_id(str(user_id))
    with connect() as con:
        rows = con.execute("SELECT role, content FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]

def add_message(user_id, role, content):
    uid = canonical_user_id(str(user_id))
    with connect() as con:
        con.execute("INSERT INTO messages(user_id,role,content) VALUES(?,?,?)", (uid, role, content))

def canonical_user_id(user_id):
    with connect() as con:
        row = con.execute("SELECT telegram_user_id FROM user_links WHERE mobile_user_id=?", (str(user_id),)).fetchone()
    return str(row["telegram_user_id"]) if row else str(user_id)

def create_link_code(telegram_user_id, code, expires_at):
    with connect() as con:
        con.execute("DELETE FROM link_codes WHERE expires_at < datetime('now')")
        con.execute("INSERT OR REPLACE INTO link_codes(code,telegram_user_id,expires_at) VALUES(?,?,?)",
                    (code, str(telegram_user_id), expires_at))

def redeem_link_code(mobile_user_id, code):
    with connect() as con:
        row = con.execute("SELECT telegram_user_id FROM link_codes WHERE code=? AND datetime(expires_at) > datetime('now')", (code,)).fetchone()
        if not row: return False
        con.execute("INSERT OR REPLACE INTO user_links(mobile_user_id,telegram_user_id) VALUES(?,?)",
                    (str(mobile_user_id), str(row["telegram_user_id"])))
        con.execute("DELETE FROM link_codes WHERE code=?", (code,))
        return True

def add_memory(user_id, content):
    uid = canonical_user_id(str(user_id))
    with connect() as con:
        cur = con.execute("INSERT INTO memories(user_id,content) VALUES(?,?)", (uid, content.strip()))
        return cur.lastrowid

def list_memories(user_id, limit=100):
    uid = canonical_user_id(str(user_id))
    with connect() as con:
        rows = con.execute("SELECT id,content,created_at FROM memories WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit)).fetchall()
    return [dict(r) for r in rows]

def delete_memory(user_id, memory_id):
    uid = canonical_user_id(str(user_id))
    with connect() as con:
        cur = con.execute("DELETE FROM memories WHERE id=? AND user_id=?", (memory_id, uid))
        return cur.rowcount > 0

def memory_context(user_id, limit=30):
    rows = list_memories(user_id, limit)
    return "\n".join(f"- {r['content']}" for r in reversed(rows))

def add_reminder(user_id, text, due_at, chat_id=None):
    uid = canonical_user_id(str(user_id))
    # После /link приватный Telegram chat ID совпадает с Telegram user ID.
    delivery_chat = str(chat_id) if chat_id else (uid if uid.isdigit() else None)
    with connect() as con:
        cur = con.execute("INSERT INTO reminders(user_id,chat_id,text,due_at) VALUES(?,?,?,?)",
                          (uid, delivery_chat, text.strip(), due_at))
        return cur.lastrowid

def list_reminders(user_id, include_done=False):
    uid = canonical_user_id(str(user_id))
    sql = "SELECT id,text,due_at,status,chat_id FROM reminders WHERE user_id=?"
    args = [uid]
    if not include_done: sql += " AND status='pending'"
    sql += " ORDER BY due_at"
    with connect() as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]

def due_reminders(now_iso):
    with connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM reminders WHERE status='pending' AND due_at<=? AND chat_id IS NOT NULL ORDER BY due_at LIMIT 50",
            (now_iso,)).fetchall()]

def mark_reminder_sent(reminder_id, sent=True):
    with connect() as con:
        con.execute("UPDATE reminders SET status=?,sent_at=datetime('now') WHERE id=? AND status='pending'",
                    ("sent" if sent else "failed", reminder_id))

def delete_reminder(user_id, reminder_id):
    uid = canonical_user_id(str(user_id))
    with connect() as con:
        cur = con.execute("DELETE FROM reminders WHERE id=? AND user_id=? AND status='pending'", (reminder_id, uid))
        return cur.rowcount > 0

def add_event(user_id, title, starts_at, ends_at=None, notes=""):
    uid = canonical_user_id(str(user_id))
    with connect() as con:
        cur = con.execute("INSERT INTO calendar_events(user_id,title,starts_at,ends_at,notes) VALUES(?,?,?,?,?)",
                          (uid,title.strip(),starts_at,ends_at,notes.strip()))
        return cur.lastrowid

def list_events(user_id, start_at, end_at):
    uid = canonical_user_id(str(user_id))
    with connect() as con:
        rows = con.execute("""SELECT id,title,starts_at,ends_at,notes FROM calendar_events
            WHERE user_id=? AND starts_at>=? AND starts_at<? ORDER BY starts_at""",
            (uid,start_at,end_at)).fetchall()
    return [dict(r) for r in rows]

def delete_event(user_id, event_id):
    uid = canonical_user_id(str(user_id))
    with connect() as con:
        cur = con.execute("DELETE FROM calendar_events WHERE id=? AND user_id=?", (event_id,uid))
        return cur.rowcount > 0
