# AirGPT — Security Hardening Review (Defensive)

**Scope:** Local-first review of our own app only. Static review of `clipdrop.py`
(HTTP server), `auth.py`, `hub.py`, `audit.py`, `security.py`, `access_policy.py`,
`settings.py`, `workspace_api.py`, `terminal_pty.py`, `db.py`, `license.py`, plus a
gentle localhost concurrency probe. No exploits, PoCs, or offensive payloads were
written. Findings are severity-ordered with concrete remediations.

**Trust model note (good):** `_is_local_host()` relies on the TCP peer address
(`self.client_address[0]`), not on spoofable headers like `X-Forwarded-For`. Host
detection is therefore sound. The problems below are about *which endpoints* enforce
it, and about the default open posture.

---

## Severity summary

| # | Severity | Finding | Code changed? |
|---|----------|---------|---------------|
| 1 | **Critical** | Remote code execution / arbitrary FS via OpenIDE + agent endpoints | **Yes — fixed (S0)** |
| 2 | **Critical** | Default posture is fully open (no passcode ⇒ no auth on `0.0.0.0`) | **Partial — blast radius closed (S0)** |
| 3 | **Critical** | Arbitrary file overwrite → RCE via `/api/import` zip | **Yes — fixed** |
| 4 | **High** | Passcode / join-code brute force was unthrottled | **Yes — fixed** |
| 5 | **High** | Audit / admin data exposed to any token holder | **Yes — fixed (S0)** |
| 6 | **High** | Guest could overwrite host API keys via `POST /api/settings` | **Yes — fixed** |
| 7 | **Medium** | Destructive ops (wipe all chats, delete sessions) not host-gated | **Yes — fixed (S0)** |
| 8 | **Medium** | `/data/` path handling + download policy gaps | **Yes — partial fix** |
| 9 | **Medium** | Self-DoS: `/api/info` subprocess storm under mild concurrency | No (see RESILIENCE_NOTES) |
| 10 | **Low** | CORS `*`, token-in-query, plaintext token store, log truncation | No (recommendation) |

---

## 1. Critical — Remote code execution & arbitrary filesystem via OpenIDE/agent endpoints

**Where:** `clipdrop.py` `do_POST` / `do_GET`:
`/api/terminal/exec`, `/api/fs/write`, `/api/fs/patch`, `/api/fs/read`,
`/api/fs/tree`, `/api/fs/find`, `/api/workspace/open`, `/api/git/*`,
`/api/agents/<id>/run`, `/api/cortex/queue`.

These are only guarded by `_auth_ok()`, which returns `True` for **any** valid
workspace token — and returns `True` for **everyone** when no passcode is set
(see #2). None of them call `_is_local_host(ip)`.

- `/api/workspace/open` lets a caller point the workspace root at *any* directory
  on the host (e.g. `C:\Users\...`). `/api/fs/read` then reads and `/api/fs/write`
  writes files inside that chosen root.
- `terminal_pty.run_command` has an allowlist (`python`, `node`, `npm`, `git`, …)
  and blocks shell metacharacters and `python -c`/`-m`. **But** it still allows
  `python <script.py>` / `node <file.js>`. Because the same caller can first
  `POST /api/fs/write` a script into the workspace, the allowlist is effectively
  bypassable → arbitrary code execution.
- The server binds `HOST = "0.0.0.0"` (all interfaces) and can be published to the
  public internet via the Cloudflare tunnel, so this is reachable well beyond the LAN.

**Impact:** Full host compromise (read/write files, run code) by any peer that can
reach the port — and by anyone at all in the default no-passcode state.

**Recommended remediation (not auto-applied — this is a headline "OpenIDE" feature,
so gating it changes product behavior and needs an owner decision):**
- Gate all of these behind `_is_local_host(ip)` by default, OR behind an explicit,
  host-approved "remote IDE" allowlist + a distinct capability token (not the same
  guest chat token).
- Pin the workspace root to an operator-approved directory; do not allow guests to
  call `/api/workspace/open` on arbitrary paths.
- Keep `terminal_pty` allowlisting, but treat it as defense-in-depth only, since
  write+run defeats it.

Ready-to-apply guard (per endpoint):

```python
if not _is_local_host(ip):
    return self._json(403, {"error": "host only"})
```

## 2. Critical — Default posture is fully open

**Where:** `auth.py::verify_token` returns `True` when `pass_hash` is unset;
`clipdrop.py::_auth_ok` returns `True` when `status().needs_auth` is falsey.
Live probe confirmed `/api/auth/status` ⇒ `{"needs_auth": false}` on this machine.

Out of the box (before a host sets a passcode) **every** endpoint — including the
RCE-class endpoints in #1 and the destructive ones in #7 — is unauthenticated on
`0.0.0.0`. Anyone on the same Wi‑Fi/LAN (or the tunnel) has full access.

**Recommendation:**
- Force first-run passcode setup before the server accepts any non-local request;
  until a passcode exists, bind to `127.0.0.1` only (or refuse remote peers).
- Make "expose to LAN/tunnel" an explicit, deliberate opt-in that requires a passcode.

## 3. Critical — Arbitrary file overwrite → RCE via `/api/import` — FIXED

**Where:** `clipdrop.py` `/api/import` (zip restore).

Original code extracted zip entries under `ROOT`, only skipping names containing
`..` or starting with `/`. A guest (or anyone, in the open state) could upload a zip
whose entries overwrite `clipdrop.py`, `index.html`, or `env.local` — i.e. code
execution on next restart, or secret-key tampering. Windows drive-absolute names
(`C:\...`) were not caught by the `startswith("/")` check.

**Fix applied:**
- `_is_local_host(ip)` required (restore is a host-machine maintenance action).
- Zip-slip containment: each entry is `resolve()`d and must stay within `ROOT`.
- Reject names containing `:` (drive-absolute) and `..` path segments.
- Blocklist of sensitive targets (`env.local`, `.env`, `license.json`,
  `clipdrop.py`, `config.py`) is never overwritten.

## 4. High — Passcode / join-code brute force unthrottled — FIXED

**Where:** `clipdrop.py` `/api/auth/join`, `/api/auth/verify-passcode`.

`_auth_ok` short-circuits `True` for any `/api/auth/*` path, so the existing
`_auth_fails` brute-force counter (used for token verification) never applied to
credential guessing. Passcodes may be as short as 4 characters (`auth.py`), and join
codes are 6 hex chars (~24 bits, `secrets.token_hex(3)`), both guessable at speed.

**Fix applied:** Added `_passcode_rate_limited()` / `_note_passcode_fail()` reusing
the per-IP 5‑minute window (20 attempts ⇒ HTTP 429). Local host is exempt. Failures
now also emit `auth_fail` audit events. This complements the existing PBKDF2
(120k rounds) hashing, which is good.

## 5. High — Audit & admin data exposed to any token holder

**Where:** `GET /api/audit`, `GET /api/audit/spotcheck`, `GET /api/admin/overview`,
`GET /api/admin/worker/<id>`, `POST /api/admin/validate*`.

These return the full local audit trail (peer IPs, actions, details), per-user token
usage, and worker/validation data to any caller passing `_auth_ok` — i.e. any guest
token, or anyone in the open state. This is sensitive workforce/telemetry data.

**Recommendation:** Gate all `/api/admin/*` and `/api/audit*` behind
`_is_local_host(ip)` (the admin dashboard is conceptually a host tool served at
`/admin`). Not auto-applied only in case the product intends to share a read-only
audit view with delegated admins — if not, apply the same `host only` guard.

## 6. High — Guest could overwrite host API keys — FIXED

**Where:** `POST /api/settings` → `settings.update_settings` writes provider keys
into `env.local`. Reading keys (`GET /api/settings?keys=1`) was already host-only,
but writing was not, so a guest could inject their own keys (bill the host) or point
providers at an attacker-controlled base URL.

**Fix applied:** `POST /api/settings` now requires `_is_local_host(ip)`, matching the
existing host-only gate on reading keys.

## 7. Medium — Destructive operations not host-gated

**Where:** `DELETE /api/messages` (clears **all** messages), `DELETE /api/sessions/<id>`,
`DELETE /api/messages/<id>`, `PATCH /api/sessions/<id>`.

Any token holder (or anyone in the open state) can wipe the entire chat history or
delete/rename sessions. **Recommendation:** require `_is_local_host(ip)` for the
bulk clear (`DELETE /api/messages`) at minimum, and consider scoping per-message
deletes to the owning device/session for share-guests. Not auto-applied to avoid
breaking legitimate guest self-service deletes — decide the ownership model first.

## 8. Medium — `/data/` path handling & download policy — PARTIAL FIX

**Where:** `GET /data/...` static serving; `access_policy.is_download_allowed`.

- The handler rejected `..` but did not confirm the resolved path stays inside the
  data directory, and absolute/drive-relative names could point elsewhere on the
  drive. **Fix applied:** added a `resolve().relative_to(DATA_DIR)` containment guard.
- `is_download_allowed` only enforces the allowlist in **business** mode; in personal/
  open mode any authenticated peer can download any file under `data/`. This is
  by-design for personal use but should be called out: sensitive captures live under
  `data/` and are readable by every joined guest. **Recommendation:** offer a
  "private captures" toggle even in personal mode.

## 9. Medium — Availability / self-DoS under mild concurrency

`/api/info` spawns multiple PowerShell subprocesses per request (~17 s observed) and
`/api/wait` ~2 s; the server is a `ThreadingHTTPServer` with no concurrency cap. A
gentle 12-client probe caused 53% request failure (timeouts + connection resets).
The UI polls these endpoints, so a few open tabs can degrade the host. Full details
and remediations are in `video-assets/00-handoff/RESILIENCE_NOTES.md`.

## 10. Low — Hardening backlog

- **CORS `Access-Control-Allow-Origin: *`** on all responses (incl. APIs). With
  token-in-`Authorization` this is not immediately exploitable, but tighten to the
  known origins / drop `*` for state-changing routes.
- **Token in query string** is allowed for `/data/` (`_request_token(allow_query=…)`);
  query strings leak via logs/referrer. Prefer header-only, or short-lived signed URLs.
- **Tokens stored plaintext** in `data/auth_tokens.json` / `token_meta.json`. Anyone
  with file read (see #1) can reuse them. Consider hashing stored tokens.
- **Audit log rotation** truncates by character slice (`old[-(_MAX_BYTES//2):]`),
  which can corrupt the first JSON line; rotate on line boundaries.
- **Prompt-injection scanner** (`security.py`) is regex-only — fine as
  defense-in-depth; don't treat it as a control boundary.

---

## Changes made in this pass (safe, non-feature-breaking)

All edits are in `clipdrop.py` unless noted:

1. Added `_passcode_rate_limited()` + `_note_passcode_fail()`; wired into
   `/api/auth/join` and `/api/auth/verify-passcode` (finding #4).
2. `/api/import`: host-gate + zip-slip containment + sensitive-file blocklist (#3).
3. `POST /api/settings`: host-gate (#6).
4. `GET /data/`: resolved-path containment guard (#8).

## S0 pass — centralized host-only gate (2026-07-23)

A single choke-point closes #1, #5, #7 and neuters #2's blast radius, without a
scattered per-endpoint edit and without breaking host use:

- New `_HOST_ONLY_PREFIXES` + `_is_host_only_path(path)` module helpers.
- `do_GET`, `do_POST` (after `_auth_ok`) and `do_DELETE` now return
  `403 {"error":"host only"}` when the path is a host-only surface and the peer
  is not `_is_local_host(ip)`. The host machine (127.0.0.1 / its own LAN IP)
  always passes; tunnel/LAN peers are denied on these surfaces even with a valid
  chat token or in the default no-passcode state.
- Host-only surfaces: `/api/fs/`, `/api/terminal/`, `/api/workspace`,
  `/api/git/`, `/api/agents/`, `/api/cortex/`, `/api/openide/`, `/api/openforge/`,
  `/api/admin`, `/api/audit` (finding #1 + #5).
- `do_DELETE`: bulk `DELETE /api/messages` and `DELETE /api/sessions/<id>` are
  host-only; per-message delete left for guest self-service (finding #7).

**Verification:** `_is_host_only_path` classification unit-checked (all dangerous
paths gated, chat/clipboard/`/data/` paths not over-gated); `_is_local_host`
confirmed True for 127.0.0.1/::1/own-LAN and False for remote LAN + tunnel IPs.
The chat/clipboard moat (`/api/chat/stream`, `/api/messages`, `/api/sessions`,
`/api/info`, `/data/`) is unaffected for guests.

### Still open — #2 full posture (product decision)

Blast radius is closed (a remote peer in the open state can now only chat/
clipboard — no RCE, no host-file read, no audit, no wipe). The remaining
hardening is to require a passcode before *any* remote access (bind `127.0.0.1`
until a passcode exists, make LAN/tunnel an explicit opt-in). Deferred because it
changes the zero-config phone→PC demo flow; slated for Safety Phase S1 with a
first-run passcode prompt. See `docs/STRATEGY_NEXT_PHASE.md` §2.2.

A gentle, read-only re-test tool lives at `scripts/_resilience_probe.py`.
