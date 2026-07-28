# Multiplayer YC clips

Run from repo root with demo mock live (`start_demo_mock.bat` or `AIRGPT_DEMO_MOCK=1`), then:

```bash
# One continuous ~45s short demo (title + product + end card → MP4)
AIRGPT_PW_HEADLESS=1 python video-assets/scripts/record_short_demo.py

# Per-act takes
python video-assets/scripts/record_act1_interrupt.py
python video-assets/scripts/record_act2_share.py
python video-assets/scripts/record_act3_hub.py
python video-assets/scripts/record_act4_lockdown_mock.py
python video-assets/scripts/record_act6_openvault.py
```

Cloud / CI: set `AIRGPT_PW_HEADLESS=1`.

Outputs:
- `short-demo/AirGPT_SHORT_DEMO_MOCK_*.mp4` — assembled short demo
- `act1/` … `act6/` — per-act WebM takes

See `docs/VIDEO_YC_PROMPTS.md` and `docs/VIDEO_YC_MULTIPLAYER.md`.
