"""Embedding facade for RAG — local-first, soft-fail.

Order:
1. Optional BGE / sentence-transformers if enabled (CortexOS-style)
2. Deterministic hashing embedder (always available) so sqlite-vec / cosine paths work offline

Enable with AIRGPT_RAG_EMBED=st|bge|model (process env or env.local). Unset → hash
(offline/EXE-safe, never auto-downloads). Force hash with AIRGPT_RAG_EMBED=hash|off|0.
"""
from __future__ import annotations

import hashlib
import math
import os
import struct
from functools import lru_cache
from pathlib import Path


DEFAULT_DIM = 64
BGE_MODEL_ID = "BAAI/bge-small-en-v1.5"


def _hash_embed(text: str, dim: int = DEFAULT_DIM) -> list[float]:
    """Cheap deterministic bag-of-hashes embedding (no model download)."""
    vec = [0.0] * dim
    toks = (text or "").lower().split()
    if not toks:
        toks = ["_empty_"]
    for tok in toks:
        digest = hashlib.blake2b(tok.encode("utf-8", errors="ignore"), digest_size=16).digest()
        # Mix several uint32 lanes into the vector
        for i in range(0, 16, 4):
            (n,) = struct.unpack_from("<I", digest, i)
            idx = n % dim
            sign = 1.0 if (n & 1) == 0 else -1.0
            vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _env_local_value(key: str) -> str:
    """Read a single key from env.local without importing ai_engine (keeps embed light)."""
    try:
        from config import ENV_FILE
    except Exception:
        ENV_FILE = Path(__file__).resolve().parents[1] / "env.local"
    try:
        if not ENV_FILE.is_file():
            return ""
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip()
    except Exception:
        return ""
    return ""


def _st_installed() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("sentence_transformers") is not None
    except Exception:
        return False


def _bge_cached() -> bool:
    """True when the HF hub already has BGE locally (no download needed)."""
    try:
        from huggingface_hub import try_to_load_from_cache

        p = try_to_load_from_cache(BGE_MODEL_ID, "config.json")
        return bool(p) and p != "None" and Path(str(p)).is_file()
    except Exception:
        # Fallback: common HF hub layout
        hub = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{BGE_MODEL_ID.replace('/', '--')}"
        return hub.is_dir() and any(hub.rglob("config.json"))


def resolve_embed_mode() -> str:
    """Return normalized embed mode: hash | st | bge | model | off."""
    raw = (os.environ.get("AIRGPT_RAG_EMBED") or "").strip()
    if not raw:
        raw = _env_local_value("AIRGPT_RAG_EMBED")
    mode = raw.strip().lower()
    if mode in ("hash", "off", "0", "false", "no"):
        return "hash"
    if mode in ("bge", "st", "sentence-transformers", "model"):
        return "st" if mode in ("st", "sentence-transformers", "model") else "bge"
    return "hash"


@lru_cache(maxsize=1)
def _try_model():
    """Lazy optional real embedder. Never auto-downloads unless explicitly opted in."""
    mode = resolve_embed_mode()
    if mode == "hash":
        return None

    allow_download = (os.environ.get("AIRGPT_RAG_EMBED") or _env_local_value("AIRGPT_RAG_EMBED") or "").strip().lower() in (
        "bge",
        "st",
        "sentence-transformers",
        "model",
    )

    if mode == "bge":
        try:
            from CortexOS.nlp.embedder_bge import embed_texts  # type: ignore

            def _fn(text: str) -> list[float]:
                out = embed_texts([text or ""])
                row = out[0] if out else []
                return [float(x) for x in row]

            return _fn
        except Exception:
            pass  # fall through to sentence-transformers

    if mode in ("st", "bge"):
        try:
            from sentence_transformers import SentenceTransformer

            kwargs = {}
            if not allow_download:
                kwargs["local_files_only"] = True
            model = SentenceTransformer(BGE_MODEL_ID, **kwargs)

            def _fn(text: str) -> list[float]:
                v = model.encode([text or ""], normalize_embeddings=True)[0]
                return [float(x) for x in v]

            return _fn
        except Exception:
            return None
    return None


def reset_embedder_cache() -> None:
    """Clear lazy model cache (tests / after env changes)."""
    _try_model.cache_clear()


def embed_text(text: str, *, dim: int = DEFAULT_DIM) -> list[float]:
    fn = _try_model()
    if fn is not None:
        try:
            v = fn(text)
            if v:
                return v
        except Exception:
            pass
    return _hash_embed(text, dim=dim)


def embed_texts(texts: list[str], *, dim: int = DEFAULT_DIM) -> list[list[float]]:
    return [embed_text(t, dim=dim) for t in texts]


def backend_name() -> str:
    return "model" if _try_model() is not None else "hash"


def upgrade_available() -> dict:
    """Report whether a real embedder is installed but not active (so the UI can
    offer an informed opt-in). Never auto-enables downloads — just detects the option.
    """
    if backend_name() == "model":
        return {
            "available": False,
            "active": "model",
            "upgrade": BGE_MODEL_ID,
            "hint": f"Dense embedder active ({BGE_MODEL_ID}). Rebuild spaces after switching embedders.",
        }
    if _st_installed():
        cached = _bge_cached()
        return {
            "available": True,
            "active": "hash",
            "upgrade": f"sentence-transformers · {BGE_MODEL_ID}",
            "hint": (
                f"A real embedder is installed. Set AIRGPT_RAG_EMBED=st and rebuild "
                f"for semantic/paraphrase recall (measured +0.33 recall on paraphrase queries)."
                + ("" if cached else " First run downloads ~130MB model weights.")
            ),
        }
    return {"available": False, "active": "hash"}
