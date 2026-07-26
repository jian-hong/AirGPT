# Bugfix sweep — 2026-07-25

Continues Claude's diagnostic handoff. Fixes applied in this pass:

## 1. Fabricated biographical claims (serious)

**Cause:** Text chat never fetched linked URLs and had no anti-fabrication rule, so the model guessed degrees/employers/products and presented them as fact. Double-send made two contradictory guesses look like two "answers".

**Fix (`ai_engine.py`):**
- Truthfulness rule in `TEXT_CHAT_TEMPLATE`
- `_extract_urls` + `_fetch_url_evidence` inject Linked Evidence (or an explicit "could not verify / do not invent" block)
- Domain modes no longer refuse off-domain questions

## 2. Double-send (~20s apart, two AI rows)

**Cause:** `/api/chat/stream` persists the user row as soon as the stream opens. If `sendStream()` later returned `false` (tail disconnect, `pullChat` throw, missing `done`), `send()` fell through to `POST /api/messages` and queued a second generation. No `sendInFlight` lock.

**Fix (`index.html`):**
- `sendStream` returns `{ok, opened}`; fallback only when `opened===false`
- `sendInFlight` mutex; `pullChat` failures no longer flip success → false

## 3. Image clipboard "doubling"

**Cause:** Dedupe hashed PNG *file* bytes. ICC profiles (and encode noise) made identical pixels look different, so `claim_hash` missed.

**Fix (`clipdrop.py`):** `_image_content_hash` = SHA-256 of `WxH:` + RGB `tobytes()`, used at all four image hash sites. Storage still normalizes to PNG.

## 4. New chat stuck in Engineering

**Cause:** `_server_mode = "engineering"` + `pullInfo` sync + skill pack injection → cold semiconductor refusals.

**Fix:** Server defaults → `general`; `newChat()` resets to General; `POST /api/sessions` defaults category to general.

## Still open (media)

MSN / JS-shell video pages return `"no extractable text"`. Needs headless render or `yt-dlp` — not a parser tweak. Track under media architecture.
