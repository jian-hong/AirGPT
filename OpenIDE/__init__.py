"""OpenIDE — local Agents | IDE surface (workspace, terminal, Cursor bridge, UI).

Source of truth for OpenIDE product code. Root `workspace_api` / `cursor_bridge` /
`terminal_pty` are thin compatibility shims that re-export from this package.
"""
from __future__ import annotations

from . import cursor_bridge, openvault_bridge, prompt_trends, scaffold, terminal_pty, workspace_api

__all__ = [
    "workspace_api",
    "cursor_bridge",
    "terminal_pty",
    "scaffold",
    "prompt_trends",
    "openvault_bridge",
]
