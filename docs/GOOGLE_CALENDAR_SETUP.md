# Google Calendar setup for ASEL V7

Add these environment variables to the Render service `asel-v7` (Dashboard → service → Environment):

- `GOOGLE_CLIENT_ID`: OAuth 2.0 Web application client ID from Google Cloud.
- `GOOGLE_CLIENT_SECRET`: matching OAuth client secret. Never commit or send this value in chat.
- `GOOGLE_REDIRECT_URI`: `https://asel-v7.onrender.com/api/google-calendar/callback`
- `GOOGLE_TOKEN_ENCRYPTION_KEY`: a Fernet key generated with:
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

The encryption key must be stable. Do not regenerate it after tokens have been saved, or stored credentials can no longer be decrypted.

In Google Cloud, enable Google Calendar API, add the redirect URI above to the OAuth web client, add scope `https://www.googleapis.com/auth/calendar`, and add the account as a test user while the OAuth consent screen is in Testing.

## API flow

1. Call `GET /api/google-calendar/connect?user_id=...` with header `X-Asel-Secret: ...`.
2. Open the returned `authorization_url` and approve access.
3. Google redirects to `/api/google-calendar/callback`.
4. Check `GET /api/google-calendar/status?user_id=...`.
5. Use the protected `/api/google-calendar/events` endpoints to list, create, update, and delete events.

All event timestamps must include a timezone. The default event timezone is `Asia/Almaty`.

OAuth state is single-use and expires after 10 minutes. Stored OAuth credentials are encrypted at rest using `GOOGLE_TOKEN_ENCRYPTION_KEY`.
