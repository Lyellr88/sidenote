"""Storage: migration from the 1.0.x format, atomic saves, corruption handling."""

import json
from datetime import datetime

import pytest

from cli_sidenote import storage


@pytest.fixture
def todo_file(tmp_path):
    return tmp_path / "todos.json"


# --------------------------------------------------------------- basic shape


def test_new_todo_defaults():
    todo = storage.new_todo("write tests")
    assert todo["text"] == "write tests"
    assert todo["done"] is False
    datetime.fromisoformat(todo["created"])  # parseable


def test_display_marks_done_state():
    open_todo = storage.new_todo("thing", created="2026-07-27T14:23:00")
    assert storage.display(open_todo) == "[ ] 14:23 thing"

    done_todo = storage.new_todo("thing", done=True, created="2026-07-27T14:23:00")
    assert storage.display(done_todo) == "[x] 14:23 thing"


def test_display_survives_missing_or_bad_timestamp():
    assert storage.display({"text": "no stamp"}) == "[ ] no stamp"
    assert storage.display({"text": "bad", "created": "nonsense"}) == "[ ] bad"


# ------------------------------------------------------------------ loading


def test_missing_file_is_not_an_error(todo_file):
    todos, error = storage.load(todo_file)
    assert todos == []
    assert error is None


def test_legacy_string_list_is_migrated(todo_file):
    todo_file.write_text(json.dumps(["[14:23] Fix the login bug", "[09:05] Ship it"]))
    todos, error = storage.load(todo_file)

    assert error is None
    assert [t["text"] for t in todos] == ["Fix the login bug", "Ship it"]
    assert all(t["done"] is False for t in todos)
    # Time is preserved from the old prefix; date comes from the file's mtime.
    assert datetime.fromisoformat(todos[0]["created"]).strftime("%H:%M") == "14:23"
    assert datetime.fromisoformat(todos[1]["created"]).strftime("%H:%M") == "09:05"


def test_legacy_entry_without_timestamp_still_loads(todo_file):
    todo_file.write_text(json.dumps(["no prefix here"]))
    todos, error = storage.load(todo_file)

    assert error is None
    assert todos[0]["text"] == "no prefix here"
    assert todos[0]["created"] is None


def test_legacy_migration_keeps_text_containing_brackets(todo_file):
    todo_file.write_text(json.dumps(["[14:23] Review PR [urgent]"]))
    todos, _ = storage.load(todo_file)
    assert todos[0]["text"] == "Review PR [urgent]"


def test_corrupt_file_reports_error_and_preserves_file(todo_file):
    todo_file.write_text("{not valid json")
    todos, error = storage.load(todo_file)

    assert todos == []
    assert error is not None
    # The unreadable file must survive so the user can recover it by hand.
    assert todo_file.exists()
    assert todo_file.read_text() == "{not valid json"


def test_unexpected_shape_is_reported(todo_file):
    todo_file.write_text(json.dumps("just a string"))
    todos, error = storage.load(todo_file)
    assert todos == []
    assert error is not None


# ------------------------------------------------------------------- saving


def test_round_trip_preserves_done_state(todo_file):
    todos = [storage.new_todo("a", done=True), storage.new_todo("b")]
    assert storage.save(todos, todo_file) is None

    loaded, error = storage.load(todo_file)
    assert error is None
    assert loaded == todos


def test_save_writes_versioned_payload(todo_file):
    storage.save([storage.new_todo("a")], todo_file)
    payload = json.loads(todo_file.read_text(encoding="utf-8"))
    assert payload["version"] == storage.SCHEMA_VERSION
    assert len(payload["todos"]) == 1


def test_save_leaves_no_temp_files_behind(todo_file):
    storage.save([storage.new_todo("a")], todo_file)
    leftovers = [p for p in todo_file.parent.iterdir() if p.name.startswith(".todos-")]
    assert leftovers == []


def test_save_reports_error_instead_of_raising(tmp_path):
    # A directory where the file should be: save must report, never explode,
    # because a silent failure loses todos with no warning.
    target = tmp_path / "todos.json"
    target.mkdir()
    error = storage.save([storage.new_todo("a")], target)
    assert error is not None
    assert "failed" in error.lower()


def test_save_is_atomic_on_failure(todo_file, monkeypatch):
    """A crash mid-write must not truncate the previous todo list."""
    good = [storage.new_todo("keep me")]
    storage.save(good, todo_file)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(storage.os, "replace", boom)
    error = storage.save([storage.new_todo("new")], todo_file)

    assert error is not None
    loaded, _ = storage.load(todo_file)
    assert [t["text"] for t in loaded] == ["keep me"]


def test_unicode_survives_round_trip(todo_file):
    todos = [storage.new_todo("café ☕ — naïve")]
    storage.save(todos, todo_file)
    loaded, error = storage.load(todo_file)
    assert error is None
    assert loaded[0]["text"] == "café ☕ — naïve"
