# ASEL V8 — Engineering plan and repository audit

Status: branch established; audit started. This document is a plan, not a claim that features are implemented.

## Branch safety

- Production/backup baseline: `asel-v7`
- Development branch: `asel-v8`
- V8 branch was created from V7 commit `f06475350d30e01944da09218b860ccfb731047e`.
- Do not push V8 changes to `asel-v7`; do not deploy V8 to the current Render service until acceptance tests pass.

## Repository audit — confirmed facts

- Main backend is FastAPI in `backend/main.py`; it currently exposes chat, voice, history, memory, reminders, internal events, Telegram linking, and Google Calendar endpoints.
- Chat requests call `ask_asel()` in `backend/ai.py`. The model receives text messages and stored history; there is no document attachment context pipeline yet.
- Backend dependencies currently include FastAPI, python-multipart, OpenAI SDK, PostgreSQL driver, cryptography, and Google Calendar libraries. Document parsers (PDF, DOCX, XLSX, PPTX) are not currently listed.
- The mobile client is Flutter in `ASEL_Telegram_Android_iOS/mobile/`. It currently supports text chat, voice recording/playback, settings, Telegram linking, and Google Calendar connection UI.
- Flutter dependencies currently include http, shared_preferences, record, audioplayers, path_provider, and url_launcher. No file picker dependency is present.
- Existing chat history is restored from the server. The current message model stores only text and sender direction; attachments need a richer message/attachment model.
- Google Calendar REST endpoints exist in the backend, but the current conversational `ask_asel()` flow does not yet invoke calendar tools. A connected calendar is not the same as natural-language calendar control.
- There are legacy/duplicate-looking source directories with different capitalization. Before changing build paths, verify which directory each workflow actually builds. The active mobile path referenced by the V7 workflow and current app source must be kept consistent.
- `backend/config.py` currently has a development fallback for `ASEL_API_SECRET`; V8 should fail closed in production when required secrets are absent or left at defaults.
- Current chat history is text-oriented. The V8 design must retain attachment metadata and extracted text in a controlled way without blindly treating file content as trusted instructions.

## V8 goals

1. Preserve the Asel persona, five supplied avatar assets, Russian/Kazakh/English behavior, text and voice chat.
2. Add chat attachments and document/image understanding.
3. Add file-generated outputs with safe download links.
4. Make Google Calendar operations available through natural language only after explicit OAuth connection and confirmation for consequential changes.
5. Keep V7 intact and deploy V8 independently until tested.

## File attachment feature

### Initial supported formats

- Documents: PDF, DOCX, TXT, MD
- Tables: XLSX, CSV
- Presentations: PPTX
- Images: JPG, JPEG, PNG, WEBP
- Archives: ZIP, only with strict extraction limits and path traversal protection

Unsupported or executable formats must be rejected. Do not execute macros, scripts, binaries, or embedded code.

### Proposed request flow

1. Flutter paperclip button opens the platform file picker; show filename, size, and upload progress.
2. Client uploads to an authenticated multipart endpoint using the existing owner/session identity.
3. Backend validates user authorization, extension, MIME signature, file size, archive expansion size, and file count.
4. Backend stores the upload in a per-request temporary workspace, extracts text or image content with format-specific parsers, and associates the result with the chat turn.
5. Extracted content is passed to the AI as untrusted reference material, clearly separated from system instructions. Ignore instructions embedded in documents that attempt to override assistant policy or request secrets/actions.
6. Asel responds with analysis, summary, answers, calculations, comparisons, or transformations.
7. Generated files are returned as authenticated, expiring downloads. Temporary uploads and generated artifacts are deleted according to a documented retention policy.

### Security and operational requirements

- Enforce configurable upload size limits and timeouts; start conservatively (e.g. 20 MB per file) and make limits configurable.
- Use allowlists and content sniffing; do not trust the client-supplied filename or MIME type.
- Generate server-side opaque IDs and safe filenames; never use a user filename as a filesystem path.
- Protect ZIP extraction against traversal, symlinks, nested archive bombs, excessive file counts, and excessive expanded size.
- Never execute uploaded content.
- Keep files isolated by user and request; verify ownership on every read/download.
- Do not persist raw uploads on Render's ephemeral filesystem as long-term storage. Initial implementation should process in a temporary directory and clean up reliably; durable file history requires an explicitly configured object-storage provider.
- Do not log file contents, secrets, or personal document data.
- Test malformed, oversized, encrypted, corrupted, and adversarial documents.

## Delivery phases

1. Complete repository/build-path audit and establish baseline tests.
2. Define message/attachment API contracts and Flutter message model.
3. Implement secure upload, parsing, extraction, and cleanup service.
4. Implement AI attachment context and image understanding using the configured provider's supported capabilities.
5. Add Flutter picker, attachment previews, upload progress, and download/open actions.
6. Add generated-file workflows (DOCX/XLSX/PDF/PPTX as supported) with authenticated expiring downloads.
7. Add natural-language Calendar tool routing and explicit confirmation for create/update/delete actions.
8. Harden configuration, authentication, logging, limits, and error handling.
9. Add automated tests and run Android build; verify iOS project/build readiness separately.
10. Deploy to a separate V8 backend service only after tests; keep V7 service and APK as rollback.

## Acceptance criteria for file handling

- Upload and analyze one file in each supported format.
- Ask follow-up questions about an already attached file in the same conversation.
- Compare multiple uploaded documents and calculate from spreadsheets.
- Analyze supported images.
- Produce at least one downloadable generated file and verify ownership/expiry behavior.
- Reject invalid MIME, unsupported formats, oversized files, corrupt files, and ZIP traversal attempts.
- Ensure document text cannot override system instructions or cause unauthorized external actions.
- Verify temporary files are removed on success, failure, and timeout.
- Verify V7 branch and current V7 service remain unchanged.

## Not yet implemented

At the time of this audit, no V8 attachment endpoint, Flutter file picker UI, parser dependencies, generated-file download flow, or conversational calendar tool routing has been committed.