# Cloud recording for AirGPT walkthroughs

**Status (2026-07-28):** Remote unlocked — `origin` → `https://github.com/jian-hong/AirGPT.git` (private). Cursor Cloud Agent can clone this repo.

Verify:

```powershell
cd d:\AirGPT
git remote -v
# origin  https://github.com/jian-hong/AirGPT.git (fetch/push)
```

---

## Option A — Cursor Cloud Agent (true cloud recording)

1. Cloud agent clones `jian-hong/AirGPT`.
2. Install Playwright: `pip install playwright && playwright install chromium`
3. Seed + start demo mock:
   ```powershell
   python seed_demo_mock.py --reset
   $env:AIRGPT_DEMO_MOCK=1
   Start-Process python -ArgumentList "clipdrop.py" -WindowStyle Hidden
   # wait until /api/info.demo_mock is true
   ```
4. Record short demo + acts:
   ```powershell
   $env:AIRGPT_PW_HEADLESS = "1"
   python video-assets/scripts/record_short_demo.py   # ~45s assembled MP4
   python video-assets/scripts/record_act1_interrupt.py
   python video-assets/scripts/record_act2_share.py
   python video-assets/scripts/record_act3_hub.py
   python video-assets/scripts/record_act4_lockdown_mock.py
   python video-assets/scripts/record_act6_openvault.py
   ```
5. Commit/push clips under `video-assets/03-demo-clips/multiplayer/` (or leave as PR artefacts). Short master also lands in `video-assets/07-exports/AirGPT_SHORT_DEMO_MOCK_*.mp4`.

**Note:** Set `AIRGPT_PW_HEADLESS=1` on cloud/CI (no display). Local Windows can omit it for headed capture.

---

## Option B — Local Playwright (fastest for YC cut)

```powershell
cd d:\AirGPT
.\start_demo_mock.bat
python video-assets\scripts\record_act1_interrupt.py
```

---

## Option C — Higgsfield / LTX plates

- Paste prompts from `docs/VIDEO_YC_PROMPTS.md`.
- LTX cloud needs `LTX_API_KEY` in env (currently missing on this machine → mock mode only).
- Drop plates in `video-assets/05-higgsfield-plates/` or `08-ltx2-outputs/`.
