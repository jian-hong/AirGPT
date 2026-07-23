# AirGPT — Resilience Notes (mild concurrency + fail-soft design)

Defensive resilience observations from a **gentle** localhost probe (not a DDoS) and
a fail-soft design review of the main downtime scenarios. Test tool:
`scripts/_resilience_probe.py` (read-only GETs, capped low).

## Test setup

- Target: `http://127.0.0.1:8765` (server already running, workspace uninitialized).
- Endpoints: `/api/probe`, `/api/info`, `/api/wait?since=0`, `/api/sessions?limit=20`.
- Load: **12 concurrent** workers, 160 total requests. 10 s client timeout.

## Observed results (12 concurrent clients)

```
total_requests=160  concurrency=12  wall=73.7s  rps=2.2
status_codes = { 200: 75, 0(failed): 85 }
errors       = { TimeoutError: 73, ConnectionResetError: 12 }
latency_ms   = min 169 · p50 7,624 · p90 10,016 · p99 10,523 · max 10,523
```

**53% of requests failed** (timeouts + resets) under only 12 clients. Per-endpoint
sequential timing isolates the cause:

| Endpoint | Sequential latency |
|----------|--------------------|
| `/api/probe` | ~0.36 s |
| `/api/sessions?limit=20` | ~0.14 s |
| `/api/wait?since=0` | ~2.1 s |
| `/api/info` | **~17.4 s** |

### Root cause

`/api/info` (and, to a lesser degree, `/api/wait`) call `lan_diagnostics()` /
`network_profile()` / Wi‑Fi helpers that **spawn PowerShell subprocesses on every
request**, each with multi-second timeouts, plus `_is_online()` network calls. The
server is a `ThreadingHTTPServer` with **no concurrency cap**, so N concurrent info
requests spawn N×(several) PowerShell processes, saturating CPU and the process
table. Requests queue past the client's 10 s timeout and the OS resets some
connections. The UI polls `/api/info` and `/api/wait` on an interval, so a handful of
open browser tabs can self-inflict this.

### Recommended fixes (availability)

1. **Cache expensive diagnostics.** Compute LAN/firewall/Wi‑Fi/network-profile in a
   single background thread every ~15–30 s and serve `/api/info` from a cached snapshot
   (near-instant). This is the single highest-leverage fix.
2. **Split hot vs. cold data.** Keep `/api/info` cheap (cached); expose a separate,
   rarely-polled `/api/diagnostics` for the subprocess-heavy details.
3. **Bound concurrency.** Cap worker threads (bounded pool / semaphore) and/or the
   number of concurrent subprocesses so a burst degrades gracefully instead of collapsing.
4. **Add per-IP request throttling** on the polling endpoints.
5. **Guard subprocess spawns** with a global lock + short cache so identical calls
   coalesce instead of each launching PowerShell.

`/api/probe` and DB-backed reads (`/api/sessions`) are healthy and fast — good
baselines to keep the UI responsive even when diagnostics are slow.

---

## Fail-soft design notes (downtime scenarios)

How AirGPT should degrade gracefully rather than hard-fail. Current behavior noted
where observed; the rest are design recommendations.

### 1. Tunnel drop (Cloudflare / lhr.life / serveo)

- **Current:** `tunnel_worker`/`restart_tunnel` retry providers; `_tunnel` tracks
  `healthy`; `_is_online()` falls back to BYOK keys and a 20 s-cached connectivity
  check; QR/join caches are cleared on restart.
- **Fail-soft target:** LAN/mDNS URLs must keep working when the tunnel is down (they
  do). Surface a clear "tunnel down — use LAN/hotspot" banner (message already exists
  on total failure). Invalidate published QR/share URLs promptly so guests aren't sent
  to a dead hostname. Never block local chat/clipboard on tunnel state.

### 2. SQLite lock / contention

- **Risk:** SQLite serializes writes; under many concurrent writers (multi-device
  chat + AI writes) you can hit `database is locked`. Bulk audit reads
  (`audit.recent` reads the whole file) and full-history queries add pressure.
- **Fail-soft target:** open connections with `PRAGMA journal_mode=WAL` and a
  `busy_timeout` (e.g. 5 s) so writers wait instead of erroring; wrap writes in a
  retry-with-backoff; keep transactions short; treat a persistent lock as a soft error
  ("saving… retrying") rather than dropping the message. Cap `audit.recent`/history to
  bounded reads (tail the file) to avoid O(file) scans.

### 3. Host OOM / resource exhaustion

- **Risk:** `MAX_BYTES = 100 MB` uploads are read fully into memory; `p.read_bytes()`
  loads whole files for `/data/`; the subprocess storm above; unbounded thread growth.
- **Fail-soft target:** stream large uploads/downloads instead of buffering; enforce a
  bounded thread pool; back-pressure (429) when a queue depth threshold is exceeded;
  keep an always-available lightweight health endpoint (`/api/probe`) so a supervisor
  can detect and restart. Persist chat to disk before AI work so an OOM kill never
  loses user input.

### 4. Future Redis / Postgres backend

- **Postgres:** move messages/sessions/audit off SQLite when multi-writer concurrency
  grows (see `docs/SCALING_POSTGRES_REDIS.md`). Use a connection pool with sane limits;
  on DB unavailability, degrade to a local write-ahead buffer (append-only file) and
  replay on reconnect rather than 500-ing the user.
- **Redis:** if used for rate limits / tunnel-health / presence, treat it as optional
  cache — on Redis outage, fall back to the in-process dicts already in `clipdrop.py`
  (`_auth_fails`, `_online_cache`, `_qr_join_cache`) so auth and presence still work
  (fail-open for availability, fail-closed for anything security-sensitive like rate
  limits — prefer local in-memory throttle over disabling it).
- **General principle:** every external dependency (tunnel, Redis, Postgres, provider
  APIs) must have a local-first fallback so the core promise — local clipboard + chat
  on the LAN — never goes down when the cloud does.

### Fail-soft priority ladder

1. Local clipboard + chat + capture (must never depend on cloud/tunnel/AI).
2. LAN sharing (independent of tunnel).
3. AI features (degrade to "offline — stored, export anytime", already implemented).
4. Tunnel / remote access (best-effort, clearly signposted when down).
