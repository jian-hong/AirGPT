"""Identical pixels must share one content hash (ICC / encode noise ignored)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clipdrop import _image_content_hash, _normalize_image_bytes


def _rgb_png(w: int = 64, h: int = 48, color=(40, 90, 200)) -> bytes:
    from PIL import Image

    im = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _png_with_icc(raw: bytes) -> bytes:
    """Re-encode same pixels with an ICC profile so file bytes differ."""
    from PIL import Image

    im = Image.open(io.BytesIO(raw)).convert("RGB")
    # Minimal sRGB-ish ICC blob (enough for Pillow to attach a profile)
    icc = (
        b"\x00\x00\x02\x28appl\x04\x00\x00\x00mntrRGB XYZ "
        b"\x07\xe0\x00\x01\x00\x01\x00\x00\x00\x00\x00\x00"
        + (b"\x00" * 500)
    )
    buf = io.BytesIO()
    try:
        im.save(buf, format="PNG", icc_profile=icc)
    except Exception:
        # If ICC attach fails, still re-encode so bytes differ
        im.save(buf, format="PNG", optimize=True)
    out = buf.getvalue()
    if out == raw:
        # Force different file bytes via compress level
        buf2 = io.BytesIO()
        im.save(buf2, format="PNG", compress_level=1)
        out = buf2.getvalue()
    return out


def test_same_pixels_same_hash_despite_encode_noise():
    a = _rgb_png()
    b = _png_with_icc(a)
    assert a != b  # file bytes differ
    assert _image_content_hash(a) == _image_content_hash(b)


def test_normalize_then_hash_stable():
    raw = _rgb_png(80, 60, (10, 20, 30))
    n1 = _normalize_image_bytes(raw)
    n2 = _normalize_image_bytes(_png_with_icc(raw))
    assert _image_content_hash(n1) == _image_content_hash(n2)


def test_different_pixels_different_hash():
    a = _rgb_png(color=(1, 2, 3))
    b = _rgb_png(color=(200, 100, 50))
    assert _image_content_hash(a) != _image_content_hash(b)
