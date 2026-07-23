"""Context engineering — OpenIDE / AirGPT local-first copy (mirrors CortexOS).

Prefer ``CortexOS.context_engineering`` when the engine is on PYTHONPATH; this
package keeps agent runs working offline.
"""
from __future__ import annotations

from .assembler import AssembledContext, ContextRequest, assemble_context
from .budget import estimate_tokens, layer_budgets
from .compaction import clear_stale_tool_results, compact_messages
from .layers import ContextLayer, LayerId
from .notes import NoteStore, default_notes_path

__all__ = [
    "AssembledContext",
    "ContextLayer",
    "ContextRequest",
    "LayerId",
    "NoteStore",
    "assemble_context",
    "clear_stale_tool_results",
    "compact_messages",
    "default_notes_path",
    "estimate_tokens",
    "layer_budgets",
]
