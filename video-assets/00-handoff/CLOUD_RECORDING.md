# Cloud recording for AirGPT walkthroughs

**Status (2026-07-17):** Pure Cursor Cloud Agent recording is **blocked**.

## Blocker

Cursor cloud agent requires:

> environment `"cloud"` requires exactly one known git remote; found 0

On this machine, `d:\AirGPT` currently has **no `.git` directory at all** (so remotes cannot exist). Until the folder is a git repo with **exactly one** remote, Cursor Cloud Agent cannot run here.

Verify locally:

```powershell
cd d:\AirGPT
git remote -v
```

Expected when ready: one remote (e.g. `origin` → GitHub/GitLab URL).

---

## Option A — Cursor Cloud Agent (true cloud recording)

1. Initialize git if missing: `git init` (only if intentional).
2. Add **exactly one** remote, e.g. `git remote add origin <your-repo-url>`.
3. Commit / push enough that the cloud environment can clone the repo.
4. Re-run a Cursor **cloud** agent task that:
   - Starts AirGPT (or uses a documented start script).
   - Runs Playwright (or similar) and uploads/saves the `.webm` under `video-assets/03-demo-clips/`.

**Unlock reply:** “Add git remote `origin` to `<url>` and retry cloud recording.”

---

## Option B — Cloudflare Tunnel + remote browser

1. Expose local AirGPT via Cloudflare Tunnel (QR / public HTTPS URL already used by Connect).
2. Point a remote browser recording service (BrowserStack, Playwright on a VPS, etc.) at that public URL.
3. Capture the session and drop the file into `video-assets/03-demo-clips/<shot>/`.

Useful when you want “record from elsewhere” without Cursor Cloud Agent.

**Unlock reply:** “Use tunnel URL + remote browser; keep Cursor local.”

---

## Option C — Higgsfield plates + local UI capture

1. Generate cinematic B-roll / brand plates in Higgsfield → `video-assets/05-higgsfield-plates/`.
2. Keep **UI walkthroughs** as local capture (Playwright / OBS) under `video-assets/03-demo-clips/`.
3. Composite in the editor (intro timeline in `04-intro-17-07/`).

This is the hybrid path that does **not** need a git remote.

**Unlock reply:** “Proceed hybrid: Higgsfield plates + local UI clips.”

---

## What works right now

Local Playwright sample against `http://127.0.0.1:8765`:

```powershell
cd d:\AirGPT
python video-assets\scripts\record_walkthrough_sample1.py
```

Output lands in:

`video-assets/03-demo-clips/connect-tunnel/UI_CONNECT_WALKTHROUGH_sample_v01_*.webm`

Do **not** batch all shots until this sample is reviewed.
