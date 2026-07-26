"""Optional media extractors for RAG Phase 1 (audio transcript).

Video/audio suffixes are only walked when video_audio_supported() is true.
Image OCR is stubbed — never walked until OCR returns text.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".ogg"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def whisper_available() -> bool:
    try:
        import whisper  # noqa: F401

        return True
    except Exception:
        return False


def video_audio_supported() -> bool:
    """Phase 1 gate: ffmpeg + Whisper (or whisper-like) for speech transcripts."""
    return ffmpeg_available() and whisper_available()


def image_ocr_supported() -> bool:
    """Phase later — always false this pass."""
    return False


def media_skip_reason(suffix: str) -> str | None:
    s = (suffix or "").lower()
    if s in IMAGE_SUFFIXES:
        return "image needs OCR (not built)"
    if s in VIDEO_SUFFIXES | AUDIO_SUFFIXES:
        if not ffmpeg_available():
            return "video/audio needs ffmpeg"
        if not whisper_available():
            return "video/audio needs Whisper (pip install openai-whisper)"
        return None
    return None


def _run_ffmpeg_wav(src: Path, dst: Path) -> bool:
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(dst),
            ],
            check=True,
            capture_output=True,
            timeout=600,
        )
        return dst.is_file() and dst.stat().st_size > 0
    except Exception:
        return False


def transcribe_media(path: Path, *, max_seconds: int = 1800) -> str:
    """Return timestamped transcript lines, or empty on soft-fail.

    Format: [t=MM:SS] text
    """
    path = Path(path)
    if not path.is_file():
        return ""
    if not video_audio_supported():
        return ""
    try:
        import whisper
    except Exception:
        return ""

    wav: Path | None = None
    tmpdir = None
    try:
        suffix = path.suffix.lower()
        audio_path = path
        if suffix in VIDEO_SUFFIXES or suffix not in {".wav"}:
            tmpdir = tempfile.TemporaryDirectory()
            wav = Path(tmpdir.name) / "audio.wav"
            if not _run_ffmpeg_wav(path, wav):
                return ""
            audio_path = wav
        model = whisper.load_model("base")
        result = model.transcribe(str(audio_path), verbose=False)
        lines: list[str] = []
        for seg in result.get("segments") or []:
            start = float(seg.get("start") or 0.0)
            if start > max_seconds:
                break
            mm = int(start // 60)
            ss = int(start % 60)
            text = str(seg.get("text") or "").strip()
            if text:
                lines.append(f"[t={mm:02d}:{ss:02d}] {text}")
        if not lines:
            plain = str(result.get("text") or "").strip()
            if plain:
                lines.append(f"[t=00:00] {plain}")
        # Cap honesty: note truncation
        if float((result.get("segments") or [{}])[-1].get("end") or 0) > max_seconds:
            lines.append(f"[meta] transcript capped at {max_seconds}s")
        return "\n".join(lines)
    except Exception:
        return ""
    finally:
        if tmpdir is not None:
            try:
                tmpdir.cleanup()
            except Exception:
                pass
