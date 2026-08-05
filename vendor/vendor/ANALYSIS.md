# Vendor UI analysis — DbGate / RedisInsight / Outerbase

**Policy:** clones live under `D:\DMS\vendor/` (gitignored). EXTRACT patterns into DMS Vite SPA. Do not ship Electron or iframe their full apps into the appliance.

| Project | Stack | Fit for DMS | Verdict |
|---------|-------|-------------|---------|
| **dbgate** | Electron + web SQL IDE | Schema tree + table grid + CSV preview closest to Library/Data Map | **EXTRACT** — sidebar tree + read-only grid (done in LibraryPage) |
| **RedisInsight** | Electron + React | Excellent browser for Redis; wrong data plane for DuckDB/Parquet warehouse | **DO NOT USE** as product UI; borrow density/toolbar cues only |
| **outerbase-studio** | Web SQL studio | Clean table chrome; license/stack may pull cloud assumptions | **EXTRACT lightly** — not embed |

Architecture (`DMS_TECHNICAL_ARCHITECTURE.md`) already specifies: in-browser preview grid with highlighted cells; Library Data Map; Excel source-only. Embedding third-party Electron apps would violate “browser-only client” and the five-port / Caddy perimeter.

cite: vendor clones 2026-07-30
