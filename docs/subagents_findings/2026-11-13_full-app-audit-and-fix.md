keywords: [audit, security, CORS, Origin, Host header, DNS rebinding, share guest, default-deny, gate, PATCH, DELETE, /data, XSS, inline handler, data-call, sanitizer, DOMPurify, AMD loader, duplicate control, dead control, workflow, worktree, verifier, merge]
main_idea: Access rules written as "remember to check" on each route left every unremembered route open, and the host was trusted by socket address alone. Fixing the class (one gate, default-deny, trust by Host and Origin) closed 30+ findings at once. The fixes themselves introduced two serious defects that only the independent verifier caught.

# Whole-app audit and nine fix lanes

## Workflow shape used (and why)

- **Audit:** 15 agents, Sonnet (repo pin for fan-out), read-only, each running
  the app from the same checkout on its own port and data dir. 11 lenses
  (controls x3, standalone pages, two size bands, routes and duplicates, three
  security lenses, first-use clarity). The four security-relevant lenses were
  each followed by a second agent told to refute the findings by re-running
  them. Isolated context; findings returned as typed records.
- **Triage:** main session, by hand. 156 findings: 125 assigned to nine lanes
  by file region, 31 marked owner decision. RAG areas excluded.
- **Fix:** 18 agents, Sonnet, three workflows side by side (the cap is two
  agents per workflow on a 4-CPU machine). One fixer per lane in its own
  worktree and branch, reproduce first, test seen red then green; then a
  different agent re-ran every repro, attacked the fix, checked that normal
  use still worked, and repaired on a `-fix` branch. The guest-access lane was
  chained on top of the cross-site lane because both edit the request entry
  points; every other lane branched from the same commit.
- **Merge:** main session. Six small conflict hunks in `index.html`, none in
  `clipdrop.py`. Combined suites and the 27-check browser run after each
  group. Preflight on this index: PARTIAL (the 2026-11-12 file covered
  parallel build and seam checks, nothing covered access rules).

## Finding 1 - the host was whoever connected from 127.0.0.1

- **Expected:** only a person at the host computer can run commands, read
  keys, change settings.
- **Actual:** any web page open in the host's browser could. A browser will
  send a request to 127.0.0.1 for any page; the server trusted the socket
  address, answered every origin with `Access-Control-Allow-Origin: *`, and
  did not look at the Host header (so DNS rebinding worked too).
- **Repro (at 75685a3):** `curl -X POST -H 'Origin: http://evil.example' -H
  'Content-Type: text/plain' -d '{"cmd":"id"}' http://127.0.0.1:<port>/api/terminal/exec`
  returned the command output. Now 403.
- **Root-cause class:** identity inferred from the transport instead of from
  what the request says about where it came from.
- **Fix:** host trust needs a Host header naming this machine; cross-site
  requests are refused by `Origin` and by `Sec-Fetch-Site`; no wildcard CORS.
- **Invariant:** never cut on trust-boundary validation. Also: a control that
  blocks legitimate work is a failure, so an unknown Host is treated as a
  remote device (passcode path), not rejected.

## Finding 2 - every route was open unless someone remembered a check

- **Expected:** a view-only share guest sees one chat.
- **Actual:** it could list and read every chat, download the database, token
  file and passcode hash from `/data/`, mint itself a full-access token, mint
  share links for any chat, and delete any message. PATCH and DELETE skipped
  the gates entirely.
- **Repro (at 75685a3):** with a view-only share token through a tunnel Host:
  `GET /api/history`, `GET /data/auth_tokens.json`, `DELETE /api/messages/<id>`.
- **Root-cause class:** deny-list access control. Each new route was open by
  default; safety depended on memory.
- **Fix:** one `_gate` for every method; share guests are default-deny with an
  explicit allow-list; `/data/` serves a non-host caller only files that a
  chat it can see points at.
- **Invariant:** fix the root-cause class, not the symptom. Ticket #77 listed
  five such routes; the audit found the class.

## Finding 3 - the fixes introduced two serious defects

- **Expected:** a fix lane leaves the app safer.
- **Actual A:** the injection lane replaced inline handlers with a
  `data-call` listener that calls a page function by name. Chat message HTML
  could carry `data-call`, so a message could call any page function on click.
- **Actual B:** the guest lane's token store was read and rewritten without a
  lock. While phones joined, a share guest's scope row could be dropped, so
  the guest briefly became a full device; two joins at once could log every
  device out.
- **Repro:** A: a message containing `<a data-call="clearAllHistory">x</a>`.
  B: `tests/test_guest_scope.py` concurrency test, red 3 of 3 before the lock.
- **Root-cause class:** a new mechanism that trusts its input because the
  author only pictured the intended caller.
- **Fix:** sanitizer forbids `data-*`, dispatcher refuses built-ins; one lock
  around the token file read-modify-write.
- **Invariant:** adversary is not verifier. Both fixers reported success with
  green tests; a different agent told to assume the fix was broken found both.

## Finding 4 - "exact duplicate" needs the whole context, not the handler

- **Expected:** removing one of two buttons that call the same function loses
  nothing.
- **Actual:** the lane removed the top-bar sidebar button and kept an 18 px
  edge tab at 38% opacity. The sidebar starts closed up to 1400 px wide, so on
  most laptops the only way to New chat, Chats and Projects was nearly
  invisible. Its verifier confirmed the tab worked at 12 widths and passed it.
- **Repro:** fresh profile at 1280x800 on the lane branch; find the sidebar.
- **Root-cause class:** a check that proves "reachable" when the requirement
  was "findable".
- **Fix:** main session restored the button and kept both; the test now says
  why they are not a duplicate pair.
- **Invariant:** assert what the user actually receives. A screenshot looked at
  by a person-shaped reader caught what 12 scripted measurements did not.

## Finding 5 - auditors change things too

- **Expected:** a read-only audit leaves the machine as it found it.
- **Actual:** a refuter proved the unauthenticated account-link route by
  calling it, which overwrote `~/Netie/account.json` (outside the app's data
  folder) with its test value.
- **Root-cause class:** "read-only" scoped to the repo, while the app under
  test writes outside it.
- **Fix:** file removed (container only); later briefs tell agents the app can
  write outside its data folder and to restore what they change.
- **Invariant:** separate verified fact from assumption: "the audit changes
  nothing" was an assumption about the app, not a fact.

## Not verified

Real tunnel (cloudflared, ngrok); real phone and on-screen keyboard; real
provider and live Cortex; Safari and Firefox; about 40 of the 56 rewired
buttons were checked by comparing old and new arguments and resolving the
target function in a live page, not by clicking each one.
