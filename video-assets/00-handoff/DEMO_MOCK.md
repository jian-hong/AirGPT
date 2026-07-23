# DEMO / BUSINESS MOCK profile for marketing recordings

**Goal:** Record AirGPT walkthroughs without showing real emails, secrets, customer IPs, hostnames, or API keys.

**Real data is safe.** Mock uses a separate directory: `data-demo-mock/`. Your normal `./data` is never overwritten by the seed.

---

## Quick start (every recording session)

```powershell
cd d:\AirGPT
.\start_demo_mock.bat
```

This will:

1. Stop whatever is listening on `:8765`
2. Run `python seed_demo_mock.py` (idempotent seed into `data-demo-mock/`)
3. Start `clipdrop.py` with:
   - `AIRGPT_DEMO_MOCK=1`
   - `AIRGPT_DATA_DIR=...\data-demo-mock`
   - Fake LAN IP `10.10.20.42` and hostname `DEMO-LAPTOP`

Confirm mock is active:

```powershell
(Invoke-RestMethod http://127.0.0.1:8765/api/info).demo_mock
# expect: True
```

Record Connect + Tunnel sample:

```powershell
python video-assets\scripts\record_walkthrough_sample1.py
```

Output lands in:

`video-assets/03-demo-clips/connect-tunnel/UI_CONNECT_WALKTHROUGH_sample_v01_MOCK_*.webm`

(and `.mp4` if ffmpeg is on PATH)

The recorder **refuses** to capture if `demo_mock` is not true.

---

## Manual enable (no bat)

```powershell
cd d:\AirGPT
python seed_demo_mock.py --reset   # optional wipe + reseed
$env:AIRGPT_DEMO_MOCK = "1"
$env:AIRGPT_DATA_DIR = "d:\AirGPT\data-demo-mock"
$env:AIRGPT_DEMO_LAN_IP = "10.10.20.42"
$env:AIRGPT_DEMO_HOSTNAME = "DEMO-LAPTOP"
# stop real server on 8765 first, then:
python clipdrop.py
```

---

## What the seed includes

| Surface | Mock content |
|--------|----------------|
| License | Business SKU · `demo.admin@example.com` · fake key |
| Workers / devices | Alex / Jordan / Sam + DEMO Host · IPs `10.10.20.x` |
| Chat sessions | Connect/Tunnel, Engineering diagram, Whiteboard, OpenForge |
| Images | `files/demo_engineering_diagram.png`, `files/demo_whiteboard.png` |
| Vault | DEMO markdown under `vault/engineering` + `vault/general` |
| Audit | Fixture lines labeled DEMO / BUSINESS MOCK |
| Network | Fixture LAN `10.10.20.42` (also forced in-process when `AIRGPT_DEMO_MOCK=1`) |

Marker files in the mock dir:

- `data-demo-mock/DEMO_MOCK.txt`
- `data-demo-mock/DEMO_PROFILE.json`

---

## Switch back to real data

1. Close the DEMO MOCK server window (or kill the PID on `:8765`).
2. Run `start.bat` or `restart.bat` **without** `AIRGPT_DEMO_MOCK` set.
3. Confirm: `(Invoke-RestMethod http://127.0.0.1:8765/api/info).demo_mock` → empty/false, and `data_dir` ends with `\data`.

---

## Camera hygiene checklist

- [ ] `/api/info.demo_mock === true` before record
- [ ] No Settings / API key panels on screen
- [ ] Tunnel URL may be a public trycloudflare link (ephemeral) — avoid lingering on real LAN IPs (mock forces `10.10.20.42`)
- [ ] Prefer clips named with `_MOCK_`
- [ ] Re-seed with `--reset` if mock chats get messy during takes

---

## Scripts

| Path | Role |
|------|------|
| `seed_demo_mock.py` | Build / refresh mock profile |
| `start_demo_mock.bat` | Seed + launch on mock data dir |
| `video-assets/scripts/record_walkthrough_sample1.py` | Playwright Connect walkthrough (mock-gated) |
| `config.py` | `AIRGPT_DATA_DIR` / `AIRGPT_DEMO_MOCK` switches |
