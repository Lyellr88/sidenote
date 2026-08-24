"""Storage: migration from pre-tabs formats, atomic saves, corruption handling."""

import json
from datetime import datetime

import pytest

from sidenote import storage


@pytest.fixture
def todo_file(tmp_path):
    return tmp_path / "todos.json"


# --------------------------------------------------------------- basic shape


def test_new_todo_defaults():
    todo = storage.new_todo("write tests")
    assert todo["text"] == "write tests"
    assert todo["done"] is False
    datetime.fromisoformat(todo["created"])


def test_new_tab_defaults():
    tab = storage.new_tab()
    assert tab["name"] == storage.DEFAULT_TAB_NAME
    assert tab["todos"] == []


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
    tabs, active, error = storage.load(todo_file)
    assert len(tabs) == 1
    assert tabs[0]["todos"] == []
    assert active == 0
    assert error is None


def test_legacy_string_list_is_migrated(todo_file):
    todo_file.write_text(json.dumps(["[14:23] Fix the login bug", "[09:05] Ship it"]))
    tabs, active, error = storage.load(todo_file)

    assert error is None
    assert active == 0
    assert len(tabs) == 1
    todos = tabs[0]["todos"]
    assert [t["text"] for t in todos] == ["Fix the login bug", "Ship it"]
    assert all(t["done"] is False for t in todos)
    assert datetime.fromisoformat(todos[0]["created"]).strftime("%H:%M") == "14:23"
    assert datetime.fromisoformat(todos[1]["created"]).strftime("%H:%M") == "09:05"


def test_legacy_entry_without_timestamp_still_loads(todo_file):
    todo_file.write_text(json.dumps(["no prefix here"]))
    tabs, _, error = storage.load(todo_file)

    assert error is None
    assert tabs[0]["todos"][0]["text"] == "no prefix here"
    assert tabs[0]["todos"][0]["created"] is None


def test_legacy_migration_keeps_text_containing_brackets(todo_file):
    todo_file.write_text(json.dumps(["[14:23] Review PR [urgent]"]))
    tabs, _, _ = storage.load(todo_file)
    assert tabs[0]["todos"][0]["text"] == "Review PR [urgent]"


def test_flat_v2_todo_list_becomes_one_tab(todo_file):
    """A pre-tabs (schema 2) file has no "tabs" key at all."""
    payload = {
        "version": 2,
        "todos": [{"text": "old style", "created": None, "done": False}],
    }
    todo_file.write_text(json.dumps(payload))
    tabs, active, error = storage.load(todo_file)

    assert error is None
    assert active == 0
    assert len(tabs) == 1
    assert tabs[0]["todos"][0]["text"] == "old style"


def test_corrupt_file_reports_error_and_preserves_file(todo_file):
    todo_file.write_text("{not valid json")
    tabs, active, error = storage.load(todo_file)

    assert len(tabs) == 1
    assert tabs[0]["todos"] == []
    assert active == 0
    assert error is not None
    assert todo_file.exists()
    assert todo_file.read_text() == "{not valid json"


def test_unexpected_shape_is_reported(todo_file):
    todo_file.write_text(json.dumps("just a string"))
    tabs, active, error = storage.load(todo_file)
    assert len(tabs) == 1
    assert tabs[0]["todos"] == []
    assert active == 0
    assert error is not None


def test_tabbed_file_round_trips_names_and_active_tab(todo_file):
    tabs = [
        storage.new_tab("Work", [storage.new_todo("ship it")]),
        storage.new_tab("Home", [storage.new_todo("groceries", done=True)]),
    ]
    assert storage.save(tabs, active_tab=1, path=todo_file) is None

    loaded, active, error = storage.load(todo_file)
    assert error is None
    assert active == 1
    assert [t["name"] for t in loaded] == ["Work", "Home"]
    assert loaded[1]["todos"][0]["done"] is True


def test_out_of_range_active_tab_falls_back_to_zero(todo_file):
    payload = {
        "version": 3,
        "active_tab": 99,
        "tabs": [{"name": "Only tab", "todos": []}],
    }
    todo_file.write_text(json.dumps(payload))
    _, active, error = storage.load(todo_file)
    assert active == 0
    assert error is None


def test_empty_tabs_list_falls_back_to_default_tab(todo_file):
    payload = {"version": 3, "active_tab": 0, "tabs": []}
    todo_file.write_text(json.dumps(payload))
    tabs, active, error = storage.load(todo_file)
    assert len(tabs) == 1
    assert active == 0
    assert error is None


# ------------------------------------------------------------------- saving


def test_round_trip_preserves_done_state(todo_file):
    todos = [storage.new_todo("a", done=True), storage.new_todo("b")]
    tabs = [storage.new_tab("Tab 1", todos)]
    assert storage.save(tabs, 0, todo_file) is None

    loaded, active, error = storage.load(todo_file)
    assert error is None
    assert active == 0
    assert loaded[0]["todos"] == todos


def test_save_writes_versioned_payload(todo_file):
    storage.save([storage.new_tab("Tab 1", [storage.new_todo("a")])], 0, todo_file)
    payload = json.loads(todo_file.read_text(encoding="utf-8"))
    assert payload["version"] == storage.SCHEMA_VERSION
    assert payload["active_tab"] == 0
    assert len(payload["tabs"]) == 1
    assert len(payload["tabs"][0]["todos"]) == 1


def test_save_leaves_no_temp_files_behind(todo_file):
    storage.save([storage.new_tab("Tab 1", [storage.new_todo("a")])], 0, todo_file)
    leftovers = [p for p in todo_file.parent.iterdir() if p.name.startswith(".todos-")]
    assert leftovers == []


def test_save_reports_error_instead_of_raising(tmp_path):
    target = tmp_path / "todos.json"
    target.mkdir()
    error = storage.save([storage.new_tab("Tab 1", [storage.new_todo("a")])], 0, target)
    assert error is not None
    assert "failed" in error.lower()


def test_save_is_atomic_on_failure(todo_file, monkeypatch):
    """A crash mid-write must not truncate the previous todo list."""
    good = [storage.new_tab("Tab 1", [storage.new_todo("keep me")])]
    storage.save(good, 0, todo_file)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(storage.os, "replace", boom)
    error = storage.save(
        [storage.new_tab("Tab 1", [storage.new_todo("new")])], 0, todo_file
    )

    assert error is not None
    loaded, _, _ = storage.load(todo_file)
    assert [t["text"] for t in loaded[0]["todos"]] == ["keep me"]


def test_unicode_survives_round_trip(todo_file):
    tabs = [storage.new_tab("café ☕", [storage.new_todo("café ☕ — naïve")])]
    storage.save(tabs, 0, todo_file)
    loaded, _, error = storage.load(todo_file)
    assert error is None
    assert loaded[0]["name"] == "café ☕"
    assert loaded[0]["todos"][0]["text"] == "café ☕ — naïve"
