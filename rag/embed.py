"""Embedding facade for RAG — local-first, soft-fail.

Order:
1. Optional BGE / sentence-transformers if installed (CortexOS-style)
2. Deterministic hashing embedder (always available) so sqlite-vec / cosine paths work offline
"""
from __future__ import annotations

import hashlib
import math
import struct
from functools import lru_cache


DEFAULT_DIM = 64


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


@lru_cache(maxsize=1)
def _try_model():
    """Lazy optional real embedder. Opt-in only — never auto-download models.

    Set AIRGPT_RAG_EMBED=bge to try CortexOS BGE or a local sentence-transformers model.
    Default stays deterministic hash (EXE-friendly, offline).
    """
    import os

    mode = (os.environ.get("AIRGPT_RAG_EMBED") or "").strip().lower()
    if mode not in ("bge", "st", "sentence-transformers", "model"):
        return None
    try:
        from CortexOS.nlp.embedder_bge import embed_texts  # type: ignore

        def _fn(text: str) -> list[float]:
            out = embed_texts([text or ""])
            row = out[0] if out else []
            return [float(x) for x in row]

        return _fn
    except Exception:
        pass
    if mode in ("st", "sentence-transformers", "model", "bge"):
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer("BAAI/bge-small-en-v1.5")

            def _fn(text: str) -> list[float]:
                v = model.encode([text or ""], normalize_embeddings=True)[0]
                return [float(x) for x in v]

            return _fn
        except Exception:
            return None
    return None


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
