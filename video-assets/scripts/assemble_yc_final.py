#!/usr/bin/env python3
"""Assemble AirGPT YC Multiplayer final cut from REC clips + procedural GEN plates.

Output: video-assets/07-exports/AirGPT_YC_Multiplayer_FINAL.mp4
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "video-assets"
CLIPS = ASSETS / "03-demo-clips"
MP = CLIPS / "multiplayer"
CONNECT = CLIPS / "connect-tunnel"
OUT_DIR = ASSETS / "07-exports"
WORK = OUT_DIR / "_assemble_work"
PLATES = WORK / "plates"
SEGMENTS = WORK / "segments"

W, H = 1920, 1080
FPS = 30

FFMPEG = shutil.which("ffmpeg") or (
    r"C:\Users\OoiJianHong\AppData\Local\Microsoft\WinGet\Packages"
    r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe"
)
FFPROBE = shutil.which("ffprobe") or str(Path(FFMPEG).with_name("ffprobe.exe"))


FONT = r"C\:/Windows/Fonts/segoeuib.ttf"


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(str(c) for c in cmd[:8]), "...")
    r = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(r.stderr[-2000:] if r.stderr else "(no stderr)", file=sys.stderr)
        raise subprocess.CalledProcessError(r.returncode, cmd, r.stdout, r.stderr)
    return r


def duration(path: Path) -> float:
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(r.stdout.strip())


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in (
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
    ):
        p = Path(name)
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def solid(color: tuple[int, int, int] = (10, 10, 12)) -> Image.Image:
    return Image.new("RGB", (W, H), color)


def qr_modules(seed: int, n: int = 21) -> np.ndarray:
    rng = np.random.default_rng(seed)
    m = rng.integers(0, 2, size=(n, n), dtype=np.uint8)
    # finder patterns
    for r0, c0 in ((0, 0), (0, n - 7), (n - 7, 0)):
        m[r0 : r0 + 7, c0 : c0 + 7] = 1
        m[r0 + 1 : r0 + 6, c0 + 1 : c0 + 6] = 0
        m[r0 + 2 : r0 + 5, c0 + 2 : c0 + 5] = 1
    return m


def draw_qr(img: Image.Image, modules: np.ndarray, cx: int, cy: int, size: int, rot: float = 0) -> None:
    n = modules.shape[0]
    cell = size / n
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=18, fill=(245, 245, 248, 255))
    pad = size * 0.08
    for r in range(n):
        for c in range(n):
            if modules[r, c]:
                x0 = pad + c * ((size - 2 * pad) / n)
                y0 = pad + r * ((size - 2 * pad) / n)
                x1 = pad + (c + 1) * ((size - 2 * pad) / n)
                y1 = pad + (r + 1) * ((size - 2 * pad) / n)
                d.rectangle((x0, y0, x1, y1), fill=(12, 12, 14, 255))
    if abs(rot) > 0.1:
        layer = layer.rotate(rot, resample=Image.BICUBIC, expand=True)
    img.paste(layer, (cx - layer.width // 2, cy - layer.height // 2), layer)


def write_frames_to_mp4(frames_dir: Path, out: Path, fps: int = FPS) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            FFMPEG,
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "f_%05d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-r",
            str(fps),
            str(out),
        ]
    )


def gen_plate_qr_shuffle(out: Path, seconds: float = 3.0) -> None:
    frames = int(seconds * FPS)
    fd = PLATES / "qr_shuffle_frames"
    fd.mkdir(parents=True, exist_ok=True)
    for i in range(frames):
        t = i / FPS
        img = solid()
        # accelerating shuffle: more codes early→late
        rate = 4 + t * 6
        count = max(1, int(rate))
        for k in range(count):
            seed = int(t * 40 + k * 17 + i)
            mods = qr_modules(seed)
            cx = int(W * (0.15 + 0.7 * ((seed * 37) % 100) / 100))
            cy = int(H * (0.2 + 0.6 * ((seed * 53) % 100) / 100))
            sz = int(180 + (seed % 120))
            rot = ((seed % 30) - 15) + t * 8
            draw_qr(img, mods, cx, cy, sz, rot)
        # vignette
        vig = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        vd = ImageDraw.Draw(vig)
        vd.ellipse((-200, -150, W + 200, H + 150), fill=(0, 0, 0, 0))
        img = Image.composite(img.convert("RGBA"), Image.new("RGBA", (W, H), (0, 0, 0, 90)), Image.new("L", (W, H), 200)).convert("RGB")
        img.save(fd / f"f_{i:05d}.png")
    write_frames_to_mp4(fd, out)


def gen_plate_mesh(out: Path, seconds: float = 2.0) -> None:
    frames = int(seconds * FPS)
    fd = PLATES / "mesh_frames"
    fd.mkdir(parents=True, exist_ok=True)
    nodes = [
        (0.50, 0.42),
        (0.28, 0.30),
        (0.72, 0.28),
        (0.22, 0.62),
        (0.78, 0.60),
        (0.42, 0.72),
        (0.60, 0.70),
        (0.50, 0.18),
    ]
    edges = [(0, 1), (0, 2), (0, 3), (0, 4), (0, 5), (0, 6), (0, 7), (1, 3), (2, 4), (5, 6)]
    fnt = font(42)
    for i in range(frames):
        t = i / max(1, frames - 1)
        img = solid()
        d = ImageDraw.Draw(img)
        # title → mesh
        title_alpha = max(0.0, 1.0 - t * 2.2)
        if title_alpha > 0.05:
            overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            od = ImageDraw.Draw(overlay)
            text = "TEAM COLLABORATION"
            # reveal letters
            n_show = max(1, int(len(text) * min(1.0, t * 3)))
            shown = text[:n_show]
            bbox = od.textbbox((0, 0), shown, font=fnt)
            tw = bbox[2] - bbox[0]
            od.text(((W - tw) // 2, H // 2 - 30), shown, fill=(230, 235, 245, int(255 * title_alpha)), font=fnt)
            img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
            d = ImageDraw.Draw(img)

        # filaments
        mesh_a = min(1.0, max(0.0, (t - 0.25) / 0.55))
        for a, b in edges:
            x1, y1 = int(nodes[a][0] * W), int(nodes[a][1] * H)
            x2, y2 = int(nodes[b][0] * W), int(nodes[b][1] * H)
            col = int(40 + 140 * mesh_a)
            d.line((x1, y1, x2, y2), fill=(col, col + 20, col + 40), width=2)
            # pulse
            p = (t * 1.8 + a * 0.1) % 1.0
            px = int(x1 + (x2 - x1) * p)
            py = int(y1 + (y2 - y1) * p)
            r = 3 + int(2 * mesh_a)
            d.ellipse((px - r, py - r, px + r, py + r), fill=(180, 220, 255))
        for nx, ny in nodes:
            x, y = int(nx * W), int(ny * H)
            r = int(6 + 10 * mesh_a)
            d.ellipse((x - r, y - r, x + r, y + r), fill=(200, 230, 255))
            d.ellipse((x - r // 2, y - r // 2, x + r // 2, y + r // 2), fill=(255, 255, 255))
        img.save(fd / f"f_{i:05d}.png")
    write_frames_to_mp4(fd, out)


def gen_plate_reverse(out: Path, seconds: float = 1.5) -> None:
    frames = int(seconds * FPS)
    fd = PLATES / "reverse_frames"
    fd.mkdir(parents=True, exist_ok=True)
    for i in range(frames):
        t = i / max(1, frames - 1)
        img = solid()
        d = ImageDraw.Draw(img)
        streak_n = 28
        for k in range(streak_n):
            y = int(40 + k * (H - 80) / streak_n)
            # snap backwards: long → short
            length = int((1.0 - t) * (400 + (k * 37) % 500))
            x = int(W * 0.55 - t * 600 + (k % 5) * 30)
            # chromatic fringes
            d.line((x, y, x + length, y), fill=(220, 80, 90), width=2)
            d.line((x, y + 1, x + length, y + 1), fill=(60, 200, 255), width=1)
            d.line((x + 2, y - 1, x + length, y - 1), fill=(240, 240, 245), width=1)
        if t > 0.85:
            img = solid()
        img.save(fd / f"f_{i:05d}.png")
    write_frames_to_mp4(fd, out)


def gen_plate_network(out: Path, seconds: float, mode: str) -> None:
    """mode: lockdown | cleared"""
    frames = int(seconds * FPS)
    fd = PLATES / f"{mode}_frames"
    fd.mkdir(parents=True, exist_ok=True)
    nodes = [(0.5, 0.45)] + [
        (0.5 + 0.28 * math.cos(a), 0.45 + 0.28 * math.sin(a)) for a in [i * math.pi / 4 for i in range(8)]
    ]
    for i in range(frames):
        t = i / max(1, frames - 1)
        img = solid()
        d = ImageDraw.Draw(img)
        if mode == "lockdown":
            # white → crimson → grey
            if t < 0.35:
                edge = (200, 210, 230)
                node = (230, 240, 255)
            elif t < 0.55:
                u = (t - 0.35) / 0.2
                edge = (int(200 + 40 * u), int(210 - 150 * u), int(230 - 160 * u))
                node = (int(230 - 40 * u), int(80 + 20 * u), int(90 + 10 * u))
            else:
                edge = (70, 70, 75)
                node = (90, 90, 95)
        else:
            # grey → green pulse outward
            pulse = t
            edge = (70, 70, 75)
            node = (90, 90, 95)
            if t > 0.15:
                edge = (80, int(120 + 80 * t), 100)
                node = (120, int(180 + 50 * t), 140)
        for j in range(1, len(nodes)):
            x1, y1 = int(nodes[0][0] * W), int(nodes[0][1] * H)
            x2, y2 = int(nodes[j][0] * W), int(nodes[j][1] * H)
            col = edge
            if mode == "cleared":
                dist = abs((j / 8) - pulse)
                if dist < 0.2:
                    col = (61, 214, 140)
            d.line((x1, y1, x2, y2), fill=col, width=3)
        for nx, ny in nodes:
            x, y = int(nx * W), int(ny * H)
            r = 10
            d.ellipse((x - r, y - r, x + r, y + r), fill=node)
        img.save(fd / f"f_{i:05d}.png")
    write_frames_to_mp4(fd, out)


def gen_plate_compress(out: Path, seconds: float = 3.0) -> None:
    frames = int(seconds * FPS)
    fd = PLATES / "compress_frames"
    fd.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    rects = [(rng.random(), rng.random(), 0.08 + 0.04 * rng.random()) for _ in range(18)]
    for i in range(frames):
        t = i / max(1, frames - 1)
        ease = t * t
        img = solid()
        d = ImageDraw.Draw(img)
        for rx, ry, rs in rects:
            cx = int(W * (rx + (0.5 - rx) * ease))
            cy = int(H * (ry + (0.5 - ry) * ease))
            side = int(W * rs * (1.0 - 0.85 * ease))
            if side < 4:
                continue
            d.rounded_rectangle(
                (cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2),
                radius=max(2, side // 10),
                outline=(180, 200, 230),
                width=2,
                fill=(20, 24, 32),
            )
        if t > 0.75:
            bloom = int(40 + 200 * ((t - 0.75) / 0.25))
            r = int(8 + 80 * ((t - 0.75) / 0.25))
            d.ellipse((W // 2 - r, H // 2 - r, W // 2 + r, H // 2 + r), fill=(bloom, bloom, min(255, bloom + 20)))
        img.save(fd / f"f_{i:05d}.png")
    write_frames_to_mp4(fd, out)


def gen_plate_devices(out: Path, seconds: float = 3.5) -> None:
    frames = int(seconds * FPS)
    fd = PLATES / "devices_frames"
    fd.mkdir(parents=True, exist_ok=True)
    # grab stills from recordings for screen content
    stills = []
    for src in (
        MP / "act1" / "act1_host_20260728_022907.webm",
        MP / "act3" / "act3_hub_20260728_022400.webm",
        MP / "act1" / "act1_peer_20260728_022907.webm",
    ):
        still = PLATES / f"still_{src.stem}.png"
        if not still.exists():
            run(
                [
                    FFMPEG,
                    "-y",
                    "-ss",
                    "4",
                    "-i",
                    str(src),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(still),
                ]
            )
        stills.append(Image.open(still).convert("RGB"))

    for i in range(frames):
        t = i / max(1, frames - 1)
        img = solid()
        d = ImageDraw.Draw(img)
        # unfold scale
        s = min(1.0, t * 1.4)
        devices = [
            ("laptop", 0.22, 0.52, 0.34, 0.28, stills[0]),
            ("ipad", 0.50, 0.50, 0.22, 0.36, stills[1]),
            ("phone", 0.76, 0.52, 0.12, 0.34, stills[2]),
        ]
        for name, cx, cy, dw, dh, still in devices:
            cw = int(W * dw * s)
            ch = int(H * dh * s)
            if cw < 8 or ch < 8:
                continue
            x0 = int(cx * W - cw / 2)
            y0 = int(cy * H - ch / 2)
            # bezel
            pad = 10 if name != "phone" else 8
            radius = 28 if name == "phone" else (22 if name == "ipad" else 12)
            d.rounded_rectangle((x0 - pad, y0 - pad, x0 + cw + pad, y0 + ch + pad), radius=radius, fill=(28, 30, 34))
            screen = still.resize((cw, ch), Image.LANCZOS)
            mask = Image.new("L", (cw, ch), 0)
            md = ImageDraw.Draw(mask)
            md.rounded_rectangle((0, 0, cw - 1, ch - 1), radius=max(4, radius - 8), fill=255)
            img.paste(screen, (x0, y0), mask)
            if name == "phone":
                # notch
                d.rounded_rectangle(
                    (x0 + cw // 2 - 22, y0 + 6, x0 + cw // 2 + 22, y0 + 14),
                    radius=4,
                    fill=(12, 12, 14),
                )
            if name == "laptop":
                # base
                d.polygon(
                    [
                        (x0 - 20, y0 + ch + pad),
                        (x0 + cw + 20, y0 + ch + pad),
                        (x0 + cw + 50, y0 + ch + pad + 18),
                        (x0 - 50, y0 + ch + pad + 18),
                    ],
                    fill=(36, 38, 42),
                )
        img.save(fd / f"f_{i:05d}.png")
    write_frames_to_mp4(fd, out)


def gen_endcard(out: Path, seconds: float = 4.0) -> None:
    frames = int(seconds * FPS)
    fd = PLATES / "endcard_frames"
    fd.mkdir(parents=True, exist_ok=True)
    mark = ASSETS / "01-logos" / "airgpt" / "concepts" / "B-glass-spark.png"
    logo = Image.open(mark).convert("RGBA") if mark.exists() else None
    f_big = font(72)
    f_sub = font(28)
    for i in range(frames):
        t = i / max(1, frames - 1)
        img = solid().convert("RGBA")
        d = ImageDraw.Draw(img)
        fade = min(1.0, t * 3)
        if logo is not None:
            lw = int(140 + 20 * math.sin(t * math.pi))
            g = logo.resize((lw, lw), Image.LANCZOS)
            img.alpha_composite(g, ((W - lw) // 2, H // 2 - 180))
        # text
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        title = "AirGPT"
        bbox = od.textbbox((0, 0), title, font=f_big)
        tw = bbox[2] - bbox[0]
        od.text(((W - tw) // 2, H // 2 - 20), title, fill=(245, 248, 255, int(255 * fade)), font=f_big)
        sub = "Multiplayer by default  ·  by NETIE.AI"
        bbox = od.textbbox((0, 0), sub, font=f_sub)
        sw = bbox[2] - bbox[0]
        od.text(((W - sw) // 2, H // 2 + 70), sub, fill=(160, 175, 195, int(220 * fade)), font=f_sub)
        img = Image.alpha_composite(img, overlay)
        img.convert("RGB").save(fd / f"f_{i:05d}.png")
    write_frames_to_mp4(fd, out)


def normalize_clip(
    src: Path,
    out: Path,
    *,
    start: float | None = None,
    dur: float | None = None,
    scale_pad: bool = True,
) -> None:
    """Scale to 1920x1080 letterboxed, h264, silent or keep no-audio consistent."""
    out.parent.mkdir(parents=True, exist_ok=True)
    args = [FFMPEG, "-y"]
    if start is not None:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(src)]
    if dur is not None:
        args += ["-t", f"{dur:.3f}"]
    if scale_pad:
        vf = (
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0a0a0c,"
            f"fps={FPS},format=yuv420p"
        )
    else:
        vf = f"fps={FPS},format=yuv420p"
    args += [
        "-vf",
        vf,
        "-an",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "fast",
        str(out),
    ]
    run(args)


def split_screen(left: Path, right: Path, out: Path, dur: float, left_ss: float = 0, right_ss: float = 0) -> None:
    """Host | Peer side-by-side with labels."""
    out.parent.mkdir(parents=True, exist_ok=True)
    left_tmp = WORK / "_split_L.mp4"
    right_tmp = WORK / "_split_R.mp4"
    normalize_clip(left, left_tmp, start=left_ss, dur=dur)
    normalize_clip(right, right_tmp, start=right_ss, dur=dur)
    # label bar PNG
    bar = WORK / "_split_labels.png"
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fnt = font(28)
    d.rectangle((20, 24, 200, 64), fill=(10, 10, 12, 180))
    d.rectangle((970, 24, 1220, 64), fill=(10, 10, 12, 180))
    d.text((36, 32), "HOST", fill=(245, 248, 255, 230), font=fnt)
    d.text((986, 32), "PEER / PHONE", fill=(245, 248, 255, 230), font=fnt)
    img.save(bar)

    # Exact even halves so hstack is precisely 1920x1080 (libx264 requires even dims).
    vf = (
        f"[0:v]scale=960:1080:force_original_aspect_ratio=decrease,"
        f"pad=960:1080:(ow-iw)/2:(oh-ih)/2:color=0x0a0a0c,setsar=1[L];"
        f"[1:v]scale=960:1080:force_original_aspect_ratio=decrease,"
        f"pad=960:1080:(ow-iw)/2:(oh-ih)/2:color=0x0a0a0c,setsar=1[R];"
        f"[L][R]hstack=inputs=2[base];"
        f"[base][2:v]overlay=0:0,format=yuv420p[v]"
    )
    run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(left_tmp),
            "-i",
            str(right_tmp),
            "-loop",
            "1",
            "-i",
            str(bar),
            "-filter_complex",
            vf,
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-t",
            f"{dur:.3f}",
            "-shortest",
            str(out),
        ]
    )


def device_frame(src: Path, out: Path, *, kind: str, start: float, dur: float) -> None:
    """Put a UI clip inside phone or iPad chrome on black."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if kind == "phone":
        sw, sh = 420, 860
        x, y = (W - sw) // 2, (H - sh) // 2
        bezel = 18
        label = "PHONE LIVE SESSION"
    else:
        sw, sh = 720, 960
        x, y = (W - sw) // 2, (H - sh) // 2 - 20
        bezel = 22
        label = "IPAD LIVE SESSION"

    framed = WORK / f"tmp_{kind}_inner.mp4"
    # Crop-fill into device screen (no letterbox bars inside chrome)
    out.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            FFMPEG,
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(src),
            "-t",
            f"{dur:.3f}",
            "-vf",
            f"scale={sw}:{sh}:force_original_aspect_ratio=increase,crop={sw}:{sh},fps={FPS},format=yuv420p",
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            "17",
            str(framed),
        ]
    )

    # chrome + caption as PNG overlay
    chrome = WORK / f"_chrome_{kind}.png"
    img = Image.new("RGBA", (W, H), (10, 10, 12, 255))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        (x - bezel, y - bezel, x + sw + bezel, y + sh + bezel),
        radius=28 if kind == "phone" else 24,
        fill=(28, 30, 34, 255),
    )
    # punch transparent hole for UI
    hole = Image.new("L", (W, H), 0)
    hd = ImageDraw.Draw(hole)
    hd.rounded_rectangle((x, y, x + sw, y + sh), radius=18 if kind == "phone" else 14, fill=255)
    # keep bezel opaque, hole will show video via overlay order: video under chrome with alpha
    # Simpler: draw bezel ring only
    img2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(img2)
    d2.rounded_rectangle(
        (x - bezel, y - bezel, x + sw + bezel, y + sh + bezel),
        radius=28 if kind == "phone" else 24,
        fill=(28, 30, 34, 255),
    )
    clear = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    img2.paste(clear, (x, y))
    fnt = font(26)
    bbox = d2.textbbox((0, 0), label, font=fnt)
    tw = bbox[2] - bbox[0]
    d2.text(((W - tw) // 2, y + sh + bezel + 28), label, fill=(220, 230, 245, 210), font=fnt)
    if kind == "phone":
        d2.rounded_rectangle((x + sw // 2 - 22, y + 8, x + sw // 2 + 22, y + 16), radius=4, fill=(12, 12, 14, 255))
    img2.save(chrome)

    vf = (
        f"[0:v]scale={sw}:{sh}:force_original_aspect_ratio=decrease,"
        f"pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2:color=0x111318[ui];"
        f"color=c=0x0a0a0c:s={W}x{H}:d={dur}:r={FPS}[bg];"
        f"[bg][ui]overlay={x}:{y}[base];"
        f"[base][1:v]overlay=0:0,format=yuv420p[v]"
    )
    run(
        [
            FFMPEG,
            "-y",
            "-i",
            str(framed),
            "-loop",
            "1",
            "-i",
            str(chrome),
            "-filter_complex",
            vf,
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-t",
            f"{dur:.3f}",
            "-shortest",
            str(out),
        ]
    )


def scan_effect_overlay(src: Path, out: Path, start: float, dur: float) -> None:
    """Connect/tunnel clip with a sweeping scan-line highlight + caption PNG."""
    out.parent.mkdir(parents=True, exist_ok=True)
    caption = WORK / "_scan_caption.png"
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fnt = font(30)
    d.rectangle((36, 28, 520, 78), fill=(10, 10, 12, 170))
    d.text((48, 40), "CONNECT / TUNNEL / SCAN", fill=(245, 248, 255, 230), font=fnt)
    img.save(caption)

    # Pre-normalize then add moving scan via blend of a generated scan bar video would be heavy;
    # use a simple bright bar via overlay of a thin PNG animated by multiple frames is overkill.
    # Use ffmpeg geq/overlay with a scrolling PNG strip.
    strip = WORK / "_scan_strip.png"
    s = Image.new("RGBA", (W, 56), (255, 255, 255, 45))
    s.save(strip)

    vf = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0a0a0c,fps={FPS}[base];"
        f"[1:v]format=rgba[cap];"
        f"[2:v]format=rgba[st];"
        f"[base][cap]overlay=0:0[b1];"
        f"[b1][st]overlay=0:mod(t*160\\,1024),format=yuv420p[v]"
    )
    run(
        [
            FFMPEG,
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(src),
            "-loop",
            "1",
            "-i",
            str(caption),
            "-loop",
            "1",
            "-i",
            str(strip),
            "-filter_complex",
            vf,
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-t",
            f"{dur:.3f}",
            "-shortest",
            str(out),
        ]
    )


def concat(paths: list[Path], out: Path) -> None:
    lst = WORK / "concat.txt"
    lines = []
    for p in paths:
        # ffmpeg concat demuxer needs escaped paths on Windows
        ap = p.resolve().as_posix().replace("'", r"\'")
        lines.append(f"file '{ap}'")
    lst.write_text("\n".join(lines), encoding="utf-8")
    run(
        [
            FFMPEG,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "16",
            "-preset",
            "medium",
            "-movflags",
            "+faststart",
            str(out),
        ]
    )


def main() -> int:
    if not Path(FFMPEG).exists():
        print("ffmpeg not found", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    PLATES.mkdir(parents=True, exist_ok=True)
    SEGMENTS.mkdir(parents=True, exist_ok=True)

    host = MP / "act1" / "act1_host_20260728_022907.webm"
    peer = MP / "act1" / "act1_peer_20260728_022907.webm"
    act2 = MP / "act2" / "act2_share_20260728_022447.webm"
    act3 = MP / "act3" / "act3_hub_20260728_022400.webm"
    act4 = MP / "act4" / "act4_lockdown_mock_20260728_022425.webm"
    act6 = MP / "act6" / "act6_openvault_20260728_022513.webm"
    connect = CONNECT / "UI_CONNECT_WALKTHROUGH_sample_v01_MOCK_20260717_172335.mp4"

    for p in (host, peer, act2, act3, act4, act6, connect):
        if not p.exists():
            print(f"MISSING: {p}", file=sys.stderr)
            return 1
        print(f"OK {p.name} {duration(p):.2f}s")

    # --- GEN plates ---
    p01 = PLATES / "01_qr.mp4"
    p02 = PLATES / "02_mesh.mp4"
    p03 = PLATES / "03_reverse.mp4"
    p04 = PLATES / "04_lockdown.mp4"
    p05 = PLATES / "05_cleared.mp4"
    p06 = PLATES / "06_compress.mp4"
    p07 = PLATES / "07_devices.mp4"
    p08 = PLATES / "08_endcard.mp4"

    need_plates = any(not p.exists() or p.stat().st_size < 1000 for p in (p01, p02, p03, p04, p05, p06, p07, p08))
    if need_plates:
        print("Generating plates...")
        gen_plate_qr_shuffle(p01, 3.0)
        gen_plate_mesh(p02, 2.2)
        gen_plate_reverse(p03, 1.4)
        gen_plate_network(p04, 2.0, "lockdown")
        gen_plate_network(p05, 2.2, "cleared")
        gen_plate_compress(p06, 2.8)
        gen_plate_devices(p07, 4.0)
        gen_endcard(p08, 4.5)
    else:
        print("Reusing existing GEN plates")

    # --- REC segments ---
    print("Building REC segments...")
    s_act1 = SEGMENTS / "act1_split.mp4"
    # Use mid portion where interrupt lands (recordings ~33s; skip first 8s setup)
    split_screen(host, peer, s_act1, dur=16.0, left_ss=8.0, right_ss=8.0)

    s_connect = SEGMENTS / "connect_scan.mp4"
    scan_effect_overlay(connect, s_connect, start=2.0, dur=10.0)

    s_phone = SEGMENTS / "phone_peer.mp4"
    device_frame(peer, s_phone, kind="phone", start=12.0, dur=6.0)

    s_ipad = SEGMENTS / "ipad_connect.mp4"
    device_frame(connect, s_ipad, kind="ipad", start=8.0, dur=7.0)

    s_act2 = SEGMENTS / "act2.mp4"
    normalize_clip(act2, s_act2)  # full ~14s — access control

    s_act3 = SEGMENTS / "act3.mp4"
    normalize_clip(act3, s_act3)

    s_act4 = SEGMENTS / "act4.mp4"
    normalize_clip(act4, s_act4)

    s_act6 = SEGMENTS / "act6.mp4"
    normalize_clip(act6, s_act6)

    # Title bump before connect (control / settings emphasis)
    s_title_connect = SEGMENTS / "title_connect.mp4"
    # 1.2s black with type
    fd = PLATES / "title_connect_frames"
    fd.mkdir(parents=True, exist_ok=True)
    fnt = font(48)
    for i in range(int(1.2 * FPS)):
        img = solid()
        d = ImageDraw.Draw(img)
        text = "Connect · Tunnel · Access"
        bbox = d.textbbox((0, 0), text, font=fnt)
        tw = bbox[2] - bbox[0]
        d.text(((W - tw) // 2, H // 2 - 24), text, fill=(230, 235, 245), font=fnt)
        img.save(fd / f"f_{i:05d}.png")
    write_frames_to_mp4(fd, s_title_connect)

    s_title_hub = SEGMENTS / "title_hub.mp4"
    fd = PLATES / "title_hub_frames"
    fd.mkdir(parents=True, exist_ok=True)
    for i in range(int(1.0 * FPS)):
        img = solid()
        d = ImageDraw.Draw(img)
        text = "Hub · Who's in · Whose AI"
        bbox = d.textbbox((0, 0), text, font=fnt)
        tw = bbox[2] - bbox[0]
        d.text(((W - tw) // 2, H // 2 - 24), text, fill=(230, 235, 245), font=fnt)
        img.save(fd / f"f_{i:05d}.png")
    write_frames_to_mp4(fd, s_title_hub)

    sequence = [
        p01,  # QR shuffle
        p02,  # mesh + TEAM COLLABORATION
        p03,  # reverse into interrupt
        s_act1,  # host | peer interrupt
        s_title_connect,
        s_connect,  # connect panel + scan sweep
        s_ipad,  # iPad framed connect
        s_act2,  # share / access control
        s_phone,  # phone peer UI
        s_title_hub,
        s_act3,  # hub
        s_act4,  # lockdown
        p04,  # lockdown wash B-roll
        p05,  # cleared
        s_act6,  # openvault
        p06,  # compress
        p07,  # three devices
        p08,  # endcard
    ]

    final = OUT_DIR / "AirGPT_YC_Multiplayer_FINAL.mp4"
    print("Concatenating...")
    concat(sequence, final)
    dur = duration(final)
    size_mb = final.stat().st_size / (1024 * 1024)
    print(f"\nDONE {final}")
    print(f"duration={dur:.1f}s ({dur/60:.2f} min) size={size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
