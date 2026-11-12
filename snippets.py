"""Saved prompts: a small library kept in DATA_DIR/snippets.json.

Each item is {id, title, body, updated_at}. The file is written atomically. A file
that cannot be read is reported to the caller and never replaced by an empty library.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid

import config

MAX_TITLE = 80
MAX_BODY = 8000
MAX_ITEMS = 200

_lock = threading.RLock()


class SnippetError(Exception):
    """Carries a plain-words message and an HTTP status for the caller."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _path() -> str:
    return os.path.join(str(config.DATA_DIR), "snippets.json")


def _load() -> list:
    p = _path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        raise SnippetError(
            "Your saved prompts file could not be read. It was left as it is. "
            "Fix or move snippets.json in the data folder, then try again.", 500)
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise SnippetError(
            "Your saved prompts file is not in the expected shape. It was left as it is.", 500)
    return data


def _save(items: list) -> None:
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp-" + uuid.uuid4().hex[:8]
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def list_all() -> list:
    with _lock:
        items = [i for i in _load() if i.get("id")]
    return sorted(items, key=lambda i: i.get("updated_at", 0), reverse=True)


def save(title, body, sid=None) -> dict:
    if not isinstance(title, str) or not isinstance(body, str):
        raise SnippetError("Title and prompt must be text.")
    title = title.strip()
    if not title:
        raise SnippetError("Give the prompt a title.")
    if not body.strip():
        raise SnippetError("The prompt is empty. Write something first.")
    if len(title) > MAX_TITLE:
        raise SnippetError(f"The title is too long. Keep it under {MAX_TITLE} characters.")
    if len(body) > MAX_BODY:
        raise SnippetError(f"The prompt is too long. Keep it under {MAX_BODY} characters.")
    with _lock:
        items = _load()
        now = time.time()
        if sid:
            for it in items:
                if it.get("id") == sid:
                    it.update(title=title, body=body, updated_at=now)
                    _save(items)
                    return it
            raise SnippetError("That prompt no longer exists.", 404)
        if len(items) >= MAX_ITEMS:
            raise SnippetError(f"You have {MAX_ITEMS} saved prompts, which is the limit. Delete one first.")
        it = {"id": uuid.uuid4().hex[:12], "title": title, "body": body, "updated_at": now}
        items.append(it)
        _save(items)
        return it


def delete(sid) -> bool:
    with _lock:
        items = _load()
        kept = [i for i in items if i.get("id") != sid]
        if len(kept) == len(items):
            raise SnippetError("That prompt no longer exists.", 404)
        _save(kept)
        return True
