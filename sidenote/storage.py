#!/usr/bin/env python3
"""
Todo persistence.

Records are dicts - ``{"text", "created", "done"}`` - not bare strings, so that
completion state (and anything added later) has somewhere to live. Todos live
inside named tabs - ``{"name", "todos"}`` - so the overlay can hold several
separate lists. Files written by 1.0.x were a flat list of
``"[14:23] do the thing"`` strings, and 1.x/2.x files were a flat todo list
with no tabs; both are migrated into a single tab on load.
"""

import contextlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

DATA_FILE = Path(os.path.expanduser("~")) / ".terminal_todos.json"

SCHEMA_VERSION = 3
MAX_TABS = 5
DEFAULT_TAB_NAME = "Tab 1"
_LEGACY_PREFIX = re.compile(r"^\[(\d{1,2}):(\d{2})\]\s*(.*)$", re.DOTALL)


_UNSET = object()


def new_todo(text, done=False, created=_UNSET):
    if created is _UNSET:
        created = datetime.now().isoformat(timespec="seconds")
    return {
        "text": text,
        "created": created,
        "done": bool(done),
    }


def new_tab(name=None, todos=None):
    return {
        "name": name or DEFAULT_TAB_NAME,
        "todos": todos if todos is not None else [],
    }


def display(todo):
    """Single-line label for the list box."""
    box = "[x]" if todo.get("done") else "[ ]"
    stamp = _short_time(todo.get("created"))
    prefix = f"{box} {stamp} " if stamp else f"{box} "
    return prefix + todo.get("text", "")


def _short_time(created):
    if not created:
        return ""
    try:
        return datetime.fromisoformat(created).strftime("%H:%M")
    except (TypeError, ValueError):
        return ""


def _migrate_legacy(raw, fallback_date):
    """Turn 1.0.x strings into records.

    The old format stored only HH:MM, so the date is genuinely unknown. We pair
    the time with the data file's last-modified date, which is the closest
    honest approximation available.
    """
    todos = []
    for item in raw:
        if isinstance(item, dict):
            todos.append(
                new_todo(
                    item.get("text", ""),
                    done=item.get("done", False),
                    created=item.get("created"),
                )
            )
            continue
        if not isinstance(item, str):
            continue
        match = _LEGACY_PREFIX.match(item)
        if match:
            hour, minute, text = (
                int(match.group(1)),
                int(match.group(2)),
                match.group(3),
            )
            try:
                created = fallback_date.replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                ).isoformat(timespec="seconds")
            except ValueError:
                created = None
            todos.append(new_todo(text, created=created))
        else:
            todos.append(new_todo(item, created=None))
    return todos


def load(path=DATA_FILE):
    """Return (tabs, active_tab, error_message). A missing file is not an error.

    ``tabs`` is never empty - callers can always index ``tabs[active_tab]``
    without checking.
    """
    path = Path(path)
    if not path.exists():
        return [new_tab()], 0, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [new_tab()], 0, f"Could not read todos: {exc}"

    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        mtime = datetime.now()

    if isinstance(raw, dict) and "tabs" in raw:
        tabs = [
            new_tab(entry.get("name"), _migrate_legacy(entry.get("todos", []), mtime))
            for entry in raw.get("tabs", [])
            if isinstance(entry, dict)
        ]
        if not tabs:
            return [new_tab()], 0, None
        active = raw.get("active_tab", 0)
        if not isinstance(active, int) or not (0 <= active < len(tabs)):
            active = 0
        return tabs, active, None

    if isinstance(raw, dict):
        items = raw.get("todos", [])
    elif isinstance(raw, list):
        items = raw
    else:
        return [new_tab()], 0, "Todo file has an unexpected shape; starting empty."

    return [new_tab(todos=_migrate_legacy(items, mtime))], 0, None


def save(tabs, active_tab=0, path=DATA_FILE):
    """Write atomically. Returns an error message, or None on success.

    Writing to a temp file in the same directory and then os.replace means a
    crash mid-write can't leave a truncated todo list behind.
    """
    path = Path(path)
    payload = {
        "version": SCHEMA_VERSION,
        "active_tab": active_tab,
        "tabs": [{"name": t["name"], "todos": t["todos"]} for t in tabs],
    }
    tmp_name = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(path.parent), prefix=".todos-", delete=False
        ) as tmp:
            tmp_name = tmp.name
            json.dump(payload, tmp, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
        return None
    except OSError as exc:
        if tmp_name and os.path.exists(tmp_name):
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
        return f"Save failed: {exc}"
