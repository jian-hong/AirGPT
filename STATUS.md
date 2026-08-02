# STATUS

**Hard cap: 60 lines.** Older narrative moves to CHANGELOG.md.

## Now

1. **Tomorrow demo path is BUSINESS MOCK** — `start_demo_mock.bat` seeds `data-demo-mock/` and
   never touches real `data/`. Confirm `demo_mock: true` before screen share.
2. **OpenVault optional for mock walkthrough** — seeded chats, hub peers, and NMD docs are
   local; live AI needs keys via OpenVault (`http://127.0.0.1:5000`) or `env.local` cache.
3. **Tunnel is best-effort** — same-WiFi LAN QR works without tunnel; tunnel needs internet
   and a fresh QR after every restart.

## Next

- Run `python scripts/verify_demo_smoke.py --require-demo-mock` before recording.
- Hard-refresh browser (`Ctrl+Shift+R`) after any server restart.
- PR [#5](https://github.com/jian-hong/AirGPT/pull/5) UI design-system (merge after demo if
  time).

## Later

- Git submodules malformed ([#3](https://github.com/jian-hong/AirGPT/issues/3)) — not demo
  blocking.
- `restart.bat` runs full `allcheck.py` (~30 endpoints); demo uses lighter smoke only.

---

## Demo runbook (5–10 min stranger)

**Prereqs:** Python 3.10+ on PATH, port 8765 free, `pip install -r requirements.txt` once.

```powershell
cd D:\AirGPT
.\start_demo_mock.bat
```

Or manually:

```powershell
cd D:\AirGPT
python seed_demo_mock.py
$env:AIRGPT_DEMO_MOCK = "1"
$env:AIRGPT_DATA_DIR = "D:\AirGPT\data-demo-mock"
python clipdrop.py
start http://127.0.0.1:8765
```

**Verify (health only):**

```powershell
python scripts\verify_demo_smoke.py --require-demo-mock
(Invoke-RestMethod http://127.0.0.1:8765/api/info).demo_mock   # True
```

**On screen:** Connect/Tunnel QR, Hub (12 DEMO peers), Vitron VDML chat, engineering diagram
session, Admin overview. Full script: `video-assets/00-handoff/DEMO_MOCK.md`.

**Return to real data:** close server, run `restart.bat` (no `AIRGPT_DEMO_MOCK`).

**Optional OpenVault** (keys + Key Vault UI): `powershell -File D:\OpenVault\scripts\windows\Start-LocalMesh.ps1 -OpenIdeUrl http://127.0.0.1:8765`
