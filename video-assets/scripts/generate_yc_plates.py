"""Submit YC Multiplayer LTX plates (cloud if LTX_API_KEY set, else mock placeholders).

Usage:
  python video-assets/scripts/generate_yc_plates.py
  set LTX_API_KEY=... && python video-assets/scripts/generate_yc_plates.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import ltx2_video  # noqa: E402

HOUSE = (
    "Cinematic product film, anamorphic 2.39:1 framing inside a 16:9 frame, "
    "shallow depth of field, deep matte-black background, cool neutral grade "
    "with a single warm practical, subtle film grain, no text artefacts, "
    "no watermark, no UI mockups, no faces in focus. "
)

PLATES = [
    ("plate01_qr_shuffle", 3, HOUSE + "A rapid shuffle of black-and-white QR codes on brushed aluminium, frosted glass, iPad, whiteboard, lanyard badge. Six per second accelerating. Macro, shallow focus, cool white key."),
    ("plate02_qr_mesh", 2, HOUSE + "Single QR dissolves into glowing node constellation with light filaments and data pulses. Laptops, server, database as pure geometry. Slow dolly-in."),
    ("plate03_reverse_riser", 2, HOUSE + "Abstract tape-stop: horizontal light streaks snap backwards with red-cyan chromatic aberration, then perfect stillness on black."),
    ("plate04_lockdown_wash", 2, HOUSE + "Network of white nodes drains to deep crimson then cold grey like a power cut. Absolute stillness. Ominous, controlled."),
    ("plate05_cleared", 2, HOUSE + "Grey network reilluminates with a green pulse from centre outward. Colour and motion return. Relief. Slow dolly out."),
    ("plate06_compress", 3, HOUSE + "Dozen rounded-rectangle screens compress into one white point of light with bloom and anamorphic flare. Push-in."),
    ("plate07_devices_blank", 3, HOUSE + "White point unfolds into laptop, tablet, phone side by side with DARK BLANK screens. Studio product shot, soft key, cool rim, slow orbit."),
]


def main() -> int:
    cap = ltx2_video.capability()
    mode = cap.get("mode") or "mock"
    print(f"LTX mode={mode} cloud={cap.get('cloud')} out={cap.get('output_dir')}")
    if mode != "cloud":
        print("NOTE: LTX_API_KEY not set — submitting MOCK placeholders. Set LTX_API_KEY for real plates.")

    jobs = []
    for pid, dur, prompt in PLATES:
        # Force duration into submit via kwargs supported by API
        r = ltx2_video.submit(prompt, duration=max(6, dur), width=1280, height=720)
        jobs.append((pid, r))
        print(f"submitted {pid} -> {r.get('id')} status={r.get('status')} mode={r.get('mode')}")
        # Write sidecar mapping
        jid = r.get("id")
        if jid:
            meta = ROOT / "video-assets" / "08-ltx2-outputs" / f"{jid}.yc_plate.json"
            meta.write_text(json.dumps({"plate": pid, "duration": dur, "prompt": prompt, "job": r}, indent=2), encoding="utf-8")

    # Wait for completion (mock is fast)
    deadline = time.time() + (120 if mode == "mock" else 900)
    while time.time() < deadline:
        done = 0
        for pid, r in jobs:
            st = ltx2_video.status(r["id"])
            if st.get("status") in ("completed", "failed"):
                done += 1
        if done >= len(jobs):
            break
        time.sleep(2)

    for pid, r in jobs:
        st = ltx2_video.status(r["id"])
        print(f"{pid}: {st.get('status')} path={st.get('result_path') or st.get('result_url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
