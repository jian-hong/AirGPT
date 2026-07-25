# What we install on the user's machine (disclosure + consent policy)

AirGPT and Cortex install software, download model weights, and fetch binaries.
Some of that happens **silently today**. This document is the inventory, the
rule we hold ourselves to, and the fixes needed to get there.

The principle: **tell people before we put something on their computer.** A
local-first product that quietly installs packages is not local-first, it is
just undisclosed. Users on metered connections, locked-down work laptops, or
small disks must not be surprised.

## The rule

1. **Disclose before install.** Name the package, the source, the approximate
   size, and why it is needed, before anything is written.
2. **Consent is explicit and per-item.** One "Install" click per capability, not
   a blanket yes buried in a first-run flow.
3. **Never silent.** No install inside a startup script, a health check, or an
   ingest path.
4. **Never global without asking twice.** `npm install -g` and system-wide
   installers change the user's machine outside our app; prefer local/venv, and
   if global is unavoidable, say so in the consent text.
5. **Degrade, do not demand.** If a dependency is missing, the feature reports
   what it needs and keeps the rest of the app working (see the good pattern
   below).
6. **Never download and execute an unverified binary.** If we fetch an
   executable, pin the version, verify a checksum or signature, and disclose it.

## Inventory (verified in code)

| What | Where | Source | Consent today |
|---|---|---|---|
| All Python requirements | `restart.bat:15` `pip install -q -r requirements.txt` | PyPI | **Silent.** `-q` hides it; runs on every restart |
| `cloudflared.exe` | `clipdrop.py:1431` `urlretrieve(...)` | GitHub releases | **Silent download of an executable**, then run |
| Marketplace packages | `marketplace.py:938` `pip install {pkg}` | PyPI | User picked an item, but the package list is not shown first |
| Marketplace npm tools | `marketplace.py:947` `npm install -g {pkg}` | npm | **Global install**, not disclosed as global |
| Model weights | `marketplace.py:970`, `model_trial.py:168` `snapshot_download` | Hugging Face | Size (often GB) not shown before download |
| BGE embedder weights | RAG dense embedding path | Hugging Face | Downloads on first ingest; no size or consent prompt |
| `sqlite-vec` | `rag/sqlite_vec_install.py` | PyPI | Opt-in helper script (acceptable) |
| `pypdf` (PDF text) | `rag/ingest.py` | PyPI | Gated and reported, never auto-installed (good) |
| `ffmpeg` + `openai-whisper` (audio/video) | `rag/media.py` | system / PyPI | Gated and reported, never auto-installed (good) |

## The good pattern (copy this)

`rag/media.py` is the model to follow. It **checks**, **gates**, and **explains**
without installing anything:

```python
def video_audio_supported() -> bool:
    return ffmpeg_available() and whisper_available()

def media_skip_reason(suffix: str) -> str | None:
    if not ffmpeg_available():
        return "video/audio needs ffmpeg"
    if not whisper_available():
        return "video/audio needs Whisper (pip install openai-whisper)"
```

The file type is only walked when support exists, and the user is told exactly
what is missing. Nothing is installed behind their back.

## Fixes needed

1. **`restart.bat`** — stop the silent `pip install -q`. Either check that
   requirements are satisfied and print what is missing, or prompt once. A
   restart script must not mutate the environment quietly.
2. **`cloudflared` download** — disclose before fetching, pin the release
   version, and verify a checksum. Downloading an `.exe` and running it with no
   disclosure or integrity check is the highest-risk item in this list.
3. **Marketplace** — show a confirmation listing the exact package names, the
   registry, the approximate size, and whether the install is **global**, before
   the first byte is fetched.
4. **Model downloads** — show the approximate size and destination before
   `snapshot_download`. Multi-GB weights on a metered connection is a real harm.
5. **Embedder first-run** — the RAG dense path downloads BGE weights on first
   ingest. Disclose on the RAG build screen ("first build downloads the local
   embedding model, about N MB, stays on this machine"), not silently.

## Dependencies panel (proposed UI)

One surface listing every optional capability:

| Capability | Needs | Status | Action |
|---|---|---|---|
| PDF text | `pypdf` | missing | Install |
| Faster vector search | `sqlite-vec` | installed | - |
| Audio/video transcripts | `ffmpeg`, `openai-whisper` | ffmpeg missing | Show how |
| Local+ vectors | `qdrant-client`, `QDRANT_URL` | not configured | Configure |

Rules for the panel: state the source and size, mark global installs, and never
pre-tick an install checkbox. "Show how" (copyable command) is a valid action
when we should not run the installer ourselves, for example a system package
like ffmpeg.

## Copy to use in the product

Short, honest, no hedging:

> Installing **openai-whisper** from PyPI (about 200 MB) so AirGPT can read
> audio and video. It stays on this machine. Continue?

Not: "Setting up your workspace..." while a gigabyte downloads.
