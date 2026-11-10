"""Backend database smoke tests, run against SQLite and PostgreSQL in CI."""
from datetime import datetime, timedelta, timezone
import uuid

from db import (
    init_db, add_memory, list_memories, delete_memory, add_message, get_history,
    add_reminder, list_reminders, due_reminders, mark_reminder_sent,
    add_event, list_events, delete_event, create_link_code, redeem_link_code,
)

def main():
    init_db()
    uid = "smoke-" + uuid.uuid4().hex
    mobile_uid = "mobile-" + uuid.uuid4().hex
    telegram_uid = "tg-" + uuid.uuid4().hex

    memory_id = add_memory(uid, "memory survives")
    assert memory_id > 0
    assert list_memories(uid)[0]["content"] == "memory survives"
    assert delete_memory(uid, memory_id)
    assert list_memories(uid) == []

    add_message(uid, "user", "hello")
    add_message(uid, "assistant", "hi")
    history = get_history(uid)
    assert [m["content"] for m in history] == ["hello", "hi"]

    due = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    reminder_id = add_reminder(uid, "test reminder", due, "123456")
    assert reminder_id > 0
    assert any(r["id"] == reminder_id for r in list_reminders(uid))
    assert any(r["id"] == reminder_id for r in due_reminders(
        (datetime.now(timezone.utc) + timedelta(minutes=6)).isoformat()
    ))
    mark_reminder_sent(reminder_id)
    assert all(r["id"] != reminder_id for r in list_reminders(uid))

    start = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    event_id = add_event(uid, "test event", start, notes="smoke")
    assert event_id > 0
    day_start = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    day_end = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    assert any(e["id"] == event_id for e in list_events(uid, day_start, day_end))
    assert delete_event(uid, event_id)

    expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    create_link_code(telegram_uid, "c" + uuid.uuid4().hex[:8], expires)
    code = "link" + uuid.uuid4().hex[:8]
    create_link_code(telegram_uid, code, expires)
    assert redeem_link_code(mobile_uid, code)
    add_message(mobile_uid, "user", "shared identity")
    assert get_history(telegram_uid)[-1]["content"] == "shared identity"

    print("Database smoke test passed.")

if __name__ == "__main__":
    main()
