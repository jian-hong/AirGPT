# Implementation plans: B, C, D, F (for Cursor agents)

Precise, self-contained tasks. All UI is in `index.html` (one owner per session;
inject self-contained blocks with one anchor). No em dash in user-facing copy.
Verify each in the running app at `127.0.0.1:8765` (reload; backend changes need
a restart via `restart.bat`).

---

## B. Back / chat button collapses Build, Agents, Platform and shows recent chats

**Goal:** pressing the Chats button (or a back affordance) closes the Build,
Agents, and Platform nav groups and returns to the recent-chats home.

**Where:**
- Chats button: `#navChats` -> `onNavChatsClick()` (index.html ~1959).
- Section open/close: `syncNavSections(activeSec)` (~4685); `updateSideNav()`
  already calls `syncNavSections(onBuild?'build':onAgents?'agents':onPlat?'platform':null)`.
- Passing `null` collapses all three groups.

**Do:**
1. In `onNavChatsClick()`, set `sideView='chats'` then call `updateSideNav()`.
   Because 'chats' is not in the build/agents/platform lists, `syncNavSections`
   receives `null` and collapses all three. Confirm `showChats()`/home render
   runs so recents show.
2. If a dedicated back arrow is wanted, add one button in the topbar that calls
   the same handler; do not add a second code path.
3. Ensure the global composer returns (it is hidden in view-only surfaces); on
   'chats' it should be visible.

**Verify:** open Build (OpenIDE), then click Chats -> Build/Agents/Platform
groups collapse, recents list shows, composer visible. `read_page` to confirm
the three groups no longer have the open class.

---

## C. No "create agent" in Settings; create-subagent is a button; agents are suggested

**Goal:** creating an agent should not live in Settings and should not be a
"type a name then create" flow. Auto-creation is for **subagents**, not agents.
Agents are **suggested/predicted** from recent trend and preferences.

**Where:**
- `createCortexAgent()` (~5573) currently opens Cortex chat and tells the user to
  type or use `/create-subagent`.
- `/create-subagent` command handler (~8182).
- Suggestion chips: `cortexSuggestionChips()` and `useCortexSuggestion()` (already
  build an agent on click).
- Any Settings entry that offers agent creation (audit `openSettings()` panels;
  the login CTA at ~2217 is workspace, not agent, and can stay).

**Do:**
1. Remove any "create agent" control from Settings panels. Grep `openSettings`
   render blocks for agent-create buttons and delete them; Settings is for
   config, not agent authoring.
2. Make create-subagent a **one-click button**, not type-then-create: add a
   "New subagent" button on the Cortex home and the Apps page that calls a new
   `createSubagentQuick()` which spawns a subagent from the active context (the
   current chat text or the last agent) via the existing subagent dispatch,
   instead of prompting for a name. Reuse the `/create-subagent` backend path.
3. **Suggest agents from trend:** add `suggestedAgentsFromTrend()` that ranks
   candidate agents from `airgpt_recent_agents` (localStorage) plus the taste
   signals used by `prefScore`/`trackPref`. Render 2-3 predicted agent chips on
   the Cortex home ("You often do X — make an agent?") that build on click via
   `useCortexSuggestion`. Keep it deterministic and local (no server call).
4. Keep the distinction explicit in copy: agents are durable and suggested;
   subagents are spawned on demand for a single task.

**Verify:** Settings has no agent-create control; the Cortex home shows a "New
subagent" button that spawns without a name prompt; predicted-agent chips appear
and build an agent on click. No console errors.

---

## D. GitHub: press to authenticate (no "how to connect" text)

**Goal:** the GitHub control starts a real auth flow on click, instead of showing
help text.

**Where:**
- Settings GitHub block (~2528): `githubAuthHelp()` ("How to connect GitHub") and
  `githubAuthStatus()`. Labelled "scaffold".
- No backend GitHub OAuth route exists yet (grep found none).

**Do:**
1. Backend (`clipdrop.py`, new routes under the host-only allowlist):
   - `POST /api/github/auth/start` -> begin the **GitHub OAuth Device Flow**
     (`POST https://github.com/login/device/code` with the app client_id and the
     requested scope). Return `user_code` + `verification_uri` + `device_code`.
   - `POST /api/github/auth/poll` -> poll `https://github.com/login/oauth/access_token`
     with the device_code until the user authorizes; store the token in the
     existing key vault (`key_vault.py`), never in localStorage or a URL.
   - `GET /api/github/status` -> report connected login + scopes.
2. UI: replace the "How to connect GitHub" button with "Connect GitHub". On
   click, call start, show the `user_code` and open `verification_uri`, then poll
   until connected and flip to "Connected as <login>".
3. Register a GitHub OAuth App (client_id) or use device-flow client_id from
   config; document it in `env.local.example`.

**Security (must surface to the user before shipping):**
- The user asked for "highest, all repos + collab". That is the broad `repo`
  scope (full read/write to every repo) plus `read:org`. Default instead to the
  **minimal** scope for the feature and let the user opt into broader scope
  explicitly; requesting full `repo` by default is a large blast radius. Put the
  scope in one config constant with a comment.
- The token is a credential: store it only in the key vault, transmit only over
  localhost, and never place it in a URL or log line.
- Device flow keeps the browser off credential entry; do not build a
  password/token paste box.

**Verify:** clicking Connect shows a device code, authorizing on GitHub flips the
UI to Connected, `GET /api/github/status` returns the login and granted scopes.

---

## F. Video: understand each frame (and audio)

**Goal:** ingest video so RAG can answer about its content, not just its filename.

**Reality:** true per-frame understanding needs a vision model and is heavy. Do it
in phases; be honest in the UI about what is indexed.

**Where:** `rag/ingest.py` `read_text_file` (add a video branch) and
`TEXT_SUFFIXES`. Follow the Office-extractor pattern already added
(`_xlsx_text`/`_docx_text`).

**Do (phased):**
1. **Phase 1 - audio transcript (cheapest, highest value):** if `ffmpeg` is
   present, extract the audio track and transcribe with a local Whisper (or the
   configured provider). Index the timestamped transcript as text. Most videos
   are carried by speech; this alone makes them answerable. Gate on ffmpeg like
   pdf is gated on pypdf (`pdf_supported()` pattern).
2. **Phase 2 - keyframe captions:** sample keyframes (scene-change or every N
   seconds via ffmpeg), caption each with a vision model, and index
   `"[t=MM:SS] <caption>"` lines. Cap frames per video (for example 60) and log
   the cap so coverage is honest, never silent truncation.
3. **Phase 3 - OCR on frames:** for slides/screens, run OCR on sampled frames and
   index the text.
4. Add `.mp4`, `.mov`, `.webm`, `.mkv` to `TEXT_SUFFIXES` only once at least
   Phase 1 works, so folder walks include them.

**Dependencies:** ffmpeg (system), a local Whisper (optional), a vision-caption
model (optional). All must be optional with graceful skip and a clear
"video needs ffmpeg" message, matching the pdf gating.

**Verify:** a short talking video ingests to a transcript; a query about a spoken
phrase retrieves the right timestamped chunk. Keyframe captions appear for a
silent clip. Frame cap is logged.

---

### Cross-cutting notes for implementers
- `index.html` and `clipdrop.py` are co-developed and change under you. Check
  mtime stability before an edit burst; confirm exact text right before each
  Edit; stage file by file.
- RAG is local-first per space (sqlite + sqlite-vec + `data/rag/<id>/`); do not
  add a redis/qdrant hard dependency.
- After an ingestion change, users must **Rebuild** affected spaces
  (RAG settings -> Rebuild whole pipeline) to reprocess existing sources.
