# ASEL V7 — Product and Technical Specification

Status: implementation baseline and acceptance criteria. This document records the agreed target; it does not claim that every integration is already implemented.

## Product goal

Asel is one persistent personal AI assistant available through Android (Honor), iOS (iPhone), and Telegram, with WhatsApp Business and calendar integrations. The assistant's core service runs server-side so it remains active when either mobile app is closed or a phone is offline.

## Confirmed owner-facing auto-reply

Use this exact Russian wording when the owner is busy and an automatic reply is enabled:

> Прошу прощения, шеф сейчас немного занят, но обязательно свяжется с вами попозже.

Do not use the former wording "мой господин..." or shortened variants as the default. Localized Kazakh and English variants may be added later, but must be reviewed before activation.

## Supported clients

- Android app for Honor.
- iOS app for iPhone.
- Telegram bot.
- One owner identity and shared server-side account state across all clients.
- Shared conversations, long-term memory, preferences, reminders, events, and integration settings.
- Push notifications on both mobile platforms.
- Flutter is the preferred cross-platform mobile framework if the source archive confirms the current app is Flutter.

## Server-side always-on operation

- The server is the source of truth for assistant logic, event processing, integrations, and durable state.
- Mobile apps are clients; closing an app must not stop Telegram/WhatsApp event processing or scheduled reminders.
- Use a durable production database (PostgreSQL recommended) rather than relying on an ephemeral local SQLite file.
- Background jobs must be restart-safe and idempotent; record event/job state so restarts do not lose or duplicate work.
- Provide health checks, structured logs, error reporting, retry/backoff, and integration status.
- Do not claim 24/7 availability beyond the hosting provider's actual service guarantees.

## Memory and conversations

- Persist user and assistant messages, timestamps, channel, and conversation/thread identifiers.
- Persist long-term memories, user preferences, active project context, reminders, calendar events, and action history.
- Conversation history and long-term memory must be shared across Android, iOS, and Telegram.
- Reopening or reinstalling a client must not reset server-side history.
- Support retrieval of prior conversation context and explicit memory management.
- Avoid keeping all history only in process memory; persist before generating the next turn.

## Telegram

- Maintain the existing Telegram bot integration.
- Support text and voice input, text and voice replies, memory commands, reminders, and shared history.
- Support Telegram video-note (round video message) output for the talking avatar, where Telegram Bot API and generated media permit it.
- A standard bot can access messages sent to it and permitted group messages; it cannot silently read the owner's unrelated private chats. Any broader personal-account integration would require a separately authorized and reviewed mechanism.
- Link Telegram identity to the same owner account used by both mobile apps.

## WhatsApp Business

- Integrate through the official WhatsApp Business Platform / Cloud API or an approved provider using webhooks.
- Receive incoming messages, identify contacts, persist message events, and send replies only under the connected business account's authorized permissions and applicable messaging rules.
- Implement busy auto-reply using the exact approved wording above.
- Do not claim access to a personal WhatsApp inbox through the Business API.

## Incoming-message monitoring (V5 requirement)

- Track incoming messages separately by messenger and by contact/conversation.
- Count messages since the owner's last reply to that specific contact; do not reset by timer.
- When a contact sends more than three messages without an owner reply, send the owner a voice alert naming that contact.
- When more than three incoming messages accumulate in a messenger, send a voice reminder to check that messenger.
- Reset only the relevant contact counter when the owner replies to that contact.
- Persist counters and an event log across restarts.
- Prevent duplicate alerts for the same threshold crossing; record alert state.
- Define and test how replies sent outside ASEL are detected via webhook/provider events.

## Calendar and planning

- Integrate a real calendar provider using explicit OAuth authorization and least-privilege scopes.
- Read, create, update, and delete events after authorization.
- Support schedule queries (today, tomorrow, date range), reminders, timezone-aware dates, and conflict/free-time checks where provider APIs allow.
- Keep provider calendar data distinct from ASEL's internal reminders/events; synchronize only with user consent.
- Current V4 internal calendar endpoints are not proof of Google Calendar connectivity.

## Voice and talking avatar

- Support Russian, Kazakh, and English.
- Improve naturalness and pronunciation of Russian and Kazakh speech; allow voice configuration.
- Transcribe incoming audio, generate an answer, synthesize speech, and generate a talking-head video with lip synchronization.
- Use the five user-supplied Asel images as identity references for one character; preserve recognizable face and overall identity while allowing approved outfit/hairstyle variations.
- Android and iOS clients display the avatar in a circular video presentation.
- Telegram sends an actual video-note when output format, duration, and API constraints are satisfied; otherwise provide a clearly identified fallback video/audio response.
- Voice-only audio attachments do not satisfy the talking-avatar requirement.

## Asel persona

- Name: Асель; fictional persona age 24; from Shymkent.
- Personal AI assistant: warm, confident, witty, proactive, moderately bold, respectful and cultured.
- Russian, Kazakh, and English; respond in the user's language, defaulting to Russian when unclear.
- Natural concise conversational style unless detail is requested.
- Never claim an external action succeeded unless the integration confirms success.

## Mobile background and notifications

- Server-side processing is authoritative and independent of mobile background execution.
- Use APNs for iOS and FCM for Android push notifications.
- Use native platform background capabilities only for permitted client-side tasks; do not promise unrestricted continuous background execution on iOS or Android.
- Support device registration, notification preferences, and secure session management.

## Security and privacy

- Store API credentials only in server-side secret storage/environment variables; never embed OpenAI, Telegram, WhatsApp, or calendar secrets in the app.
- Use authenticated mobile sessions, per-user authorization, encrypted transport, and least-privilege OAuth scopes.
- Redact secrets and sensitive message contents from logs where practical.
- Provide disconnect/revoke flows for integrations and account data export/deletion controls.

## Existing V4 baseline observed in repository

The checked-in backend currently includes FastAPI endpoints for chat, voice, memories, reminders, internal events, and Telegram account linking; Telegram bot polling; SQLite persistence; OpenAI transcription/chat; and Edge TTS. The inspected backend does not yet contain the agreed WhatsApp Business webhook integration, incoming-contact counters, Google Calendar OAuth integration, or talking-avatar/video-note pipeline. The repository currently has an Android GitHub Actions workflow that extracts a ZIP archive and builds an APK; it does not build iOS.

The repository contains a ZIP archive named `ASEL_Telegram_Android_iOS_v4_memory_calendar.zip`, but its binary contents have not yet been inspected in this implementation pass. The source layout and iOS project readiness must be verified before changing mobile code.

## Delivery phases

1. Preserve V4 and establish this V7 branch/specification.
2. Inspect and unpack the existing mobile source; verify Flutter version, dependencies, assets, Android/iOS project structure, and current app-to-API contract.
3. Replace/upgrade persistence with a durable PostgreSQL deployment and migrations; verify restart persistence.
4. Implement shared identity, conversation history, and server-side memory across clients.
5. Implement reliable background jobs, notification delivery, and Telegram event handling.
6. Implement V5 contact/messenger counters and alert deduplication.
7. Implement WhatsApp Business webhooks and authorized outbound replies.
8. Implement Google Calendar OAuth and event operations.
9. Implement talking-avatar generation, Android/iOS circular playback, and Telegram video notes.
10. Build Android APK and iOS app; run acceptance tests and publish release artifacts only after successful verification.

## Acceptance tests

- Close both mobile apps: server-side Telegram/WhatsApp event processing and scheduled jobs continue.
- Reopen either app: previous conversations and long-term memory remain available.
- Start a conversation on Telegram and continue it on either mobile client with shared context.
- Send four messages from one contact without an owner reply: exactly one voice alert identifies the contact.
- Send more than three incoming messages in a messenger: messenger-level alert is emitted once per threshold episode.
- Reply to a contact: only that contact's counter resets.
- Restart the server: conversations, memories, counters, alert state, and scheduled work remain intact.
- Create/read/update/delete a calendar event after OAuth authorization.
- Voice interaction produces synchronized talking-avatar video in the mobile app and a Telegram video note when supported.
- Android and iOS builds install and authenticate against the same backend.
- Busy auto-reply matches exactly: "Прошу прощения, шеф сейчас немного занят, но обязательно свяжется с вами попозже."
