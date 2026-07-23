# AirGPT distribute checklist (light EXE)

## Before sending / selling

1. Run `restart.bat` then:
   - `python allcheck.py`
   - `python wifi_debug.py`
   - `python security_test.py`
2. Phone smoke: new chat → 📷 send photo → appears on PC
3. Timeline chats: Today / Yesterday grouping visible; rename/pin works
4. Personal: no Business key required; clipboard + WiFi work offline
5. Business: activate key → Admin shows real devices; set access mode allowlist; unapproved IP gets 403 on `/data/`
6. Optional Cortex: set `CORTEX_API_URL` → Admin cortex status live or soft-fail standby
7. Build: `build_exe.bat` → `dist\AirGPT\AirGPT.exe` with `env.local` beside EXE
7b. Optional Space bundle: publish Netie Space, run `scripts\bundle_netie_space.ps1`, then `ISCC installer\AirGPT.iss` → `dist\installer\AirGPT-Setup.exe` (includes Netie Space when present)
8. Sign EXE with Authenticode when you have a cert (SmartScreen)
9. Never ship `env.local` with live API keys in public drops
10. Confirm NEXT UPDATE stubs only (no online Personal paywall UI)

## Optional control plane

```bat
pip install fastapi uvicorn pydantic
cd D:\AirGPT
uvicorn control_plane.app:app --host 0.0.0.0 --port 8787
```

Set `AIRGPT_API_BASE=http://YOUR_SERVER:8787` in customer Business installs.
