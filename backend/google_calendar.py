"""Google Calendar OAuth and API helpers for ASEL.

Secrets are supplied only through environment variables. OAuth tokens are encrypted
before they are persisted in the application database.
"""
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from db import connect, USE_POSTGRES, canonical_user_id

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    "https://asel-v7.onrender.com/api/google-calendar/callback",
).strip()
ENCRYPTION_KEY = os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY", "").strip()


def _fernet():
    if not ENCRYPTION_KEY:
        raise HTTPException(503, "Google Calendar encryption key is not configured")
    try:
        return Fernet(ENCRYPTION_KEY.encode("ascii"))
    except Exception as exc:
        raise HTTPException(503, "Google Calendar encryption key is invalid") from exc


def init_google_calendar_db():
    with connect() as con:
        if USE_POSTGRES:
            con.execute("""CREATE TABLE IF NOT EXISTS google_oauth_states (
                state TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS google_calendar_tokens (
                user_id TEXT PRIMARY KEY, token_ciphertext TEXT NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""")
        else:
            con.execute("""CREATE TABLE IF NOT EXISTS google_oauth_states (
                state TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires_at TEXT NOT NULL)""")
            con.execute("""CREATE TABLE IF NOT EXISTS google_calendar_tokens (
                user_id TEXT PRIMARY KEY, token_ciphertext TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")


def _client_config():
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(503, "Google OAuth client is not configured")
    return {"web": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [REDIRECT_URI],
    }}


def create_authorization_url(user_id: str):
    init_google_calendar_db()
    state = secrets.token_urlsafe(32)
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    uid = canonical_user_id(str(user_id))
    with connect() as con:
        con.execute("DELETE FROM google_oauth_states WHERE expires_at < ?",
                    (datetime.now(timezone.utc).isoformat(),))
        con.execute("INSERT INTO google_oauth_states(state,user_id,expires_at) VALUES(?,?,?)",
                    (state, uid, expiry))
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, state=state)
    flow.redirect_uri = REDIRECT_URI
    url, _ = flow.authorization_url(
        access_type="offline", prompt="consent", include_granted_scopes="true"
    )
    return url


def finish_authorization(code: str, state: str):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as con:
        row = con.execute(
            "SELECT user_id FROM google_oauth_states WHERE state=? AND expires_at>?",
            (state, now),
        ).fetchone()
        if not row:
            raise HTTPException(400, "OAuth state is invalid or expired")
        uid = str(row["user_id"])
        con.execute("DELETE FROM google_oauth_states WHERE state=?", (state,))
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, state=state)
    flow.redirect_uri = REDIRECT_URI
    flow.fetch_token(code=code)
    creds = flow.credentials
    payload = json.dumps({
        "token": creds.token, "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri, "client_id": creds.client_id,
        "client_secret": creds.client_secret, "scopes": list(creds.scopes or SCOPES),
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    })
    encrypted = _fernet().encrypt(payload.encode()).decode()
    with connect() as con:
        if USE_POSTGRES:
            con.execute("""INSERT INTO google_calendar_tokens(user_id,token_ciphertext)
                VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET
                token_ciphertext=EXCLUDED.token_ciphertext, updated_at=CURRENT_TIMESTAMP""",
                (uid, encrypted))
        else:
            con.execute("""INSERT INTO google_calendar_tokens(user_id,token_ciphertext)
                VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET
                token_ciphertext=excluded.token_ciphertext, updated_at=CURRENT_TIMESTAMP""",
                (uid, encrypted))
    return uid


def _credentials(user_id: str):
    uid = canonical_user_id(str(user_id))
    with connect() as con:
        row = con.execute(
            "SELECT token_ciphertext FROM google_calendar_tokens WHERE user_id=?", (uid,)
        ).fetchone()
    if not row:
        raise HTTPException(409, "Google Calendar is not connected")
    try:
        payload = json.loads(_fernet().decrypt(row["token_ciphertext"].encode()).decode())
    except (InvalidToken, ValueError, KeyError):
        raise HTTPException(503, "Stored Google Calendar credentials cannot be decrypted")
    expiry = datetime.fromisoformat(payload["expiry"]) if payload.get("expiry") else None
    creds = Credentials(
        token=payload.get("token"), refresh_token=payload.get("refresh_token"),
        token_uri=payload.get("token_uri"), client_id=payload.get("client_id"),
        client_secret=payload.get("client_secret"), scopes=payload.get("scopes"),
        expiry=expiry,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        payload["token"] = creds.token
        payload["expiry"] = creds.expiry.isoformat() if creds.expiry else None
        encrypted = _fernet().encrypt(json.dumps(payload).encode()).decode()
        with connect() as con:
            con.execute("UPDATE google_calendar_tokens SET token_ciphertext=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                        (encrypted, uid))
    return creds


def calendar_service(user_id: str):
    return build("calendar", "v3", credentials=_credentials(user_id), cache_discovery=False)


def connection_status(user_id: str):
    uid = canonical_user_id(str(user_id))
    with connect() as con:
        row = con.execute("SELECT 1 FROM google_calendar_tokens WHERE user_id=?", (uid,)).fetchone()
    return {"connected": bool(row)}


def list_google_events(user_id: str, time_min: str, time_max: str, max_results: int = 50):
    service = calendar_service(user_id)
    result = service.events().list(
        calendarId="primary", timeMin=time_min, timeMax=time_max,
        maxResults=max(1, min(max_results, 100)), singleEvents=True,
        orderBy="startTime",
    ).execute()
    return result.get("items", [])


def create_google_event(user_id: str, event: dict):
    return calendar_service(user_id).events().insert(
        calendarId="primary", body=event
    ).execute()


def update_google_event(user_id: str, event_id: str, patch: dict):
    return calendar_service(user_id).events().patch(
        calendarId="primary", eventId=event_id, body=patch
    ).execute()


def delete_google_event(user_id: str, event_id: str):
    calendar_service(user_id).events().delete(
        calendarId="primary", eventId=event_id
    ).execute()
    return {"deleted": True}
