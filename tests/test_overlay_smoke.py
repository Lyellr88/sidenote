"""Overlay smoke tests.

Instantiates the real tkinter UI and drives its actual methods - no mocks for
anything overlay-specific, since a fake would just re-describe the behavior
under test rather than exercise it. Storage is redirected to a per-test temp
file so these never touch the developer's real ~/.terminal_todos.json.

The tkinter UI otherwise has zero automated coverage; everything here was
manually verified by hand-rolled scripts during development and is now kept
for real so a later change gets caught instead of re-derived from scratch.
"""

import time
import tkinter as tk

import pytest

from sidenote import storage
from sidenote.terminal_overlay import TerminalOverlay


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    """A real TerminalOverlay with storage redirected to an isolated file.

    terminal_overlay.py calls storage.load()/storage.save(...) with no path
    argument, which falls back to those functions' own default parameter -
    already bound to the real DATA_FILE when storage.py was first imported.
    Patching the storage.DATA_FILE *attribute* afterwards would not change
    that default. Replacing load/save themselves does, regardless of import
    order, which matters here since other test modules import storage too.
    """
    data_file = tmp_path / "todos.json"
    real_load = storage.load
    real_save = storage.save
    monkeypatch.setattr(storage, "load", lambda path=data_file: real_load(path))
    monkeypatch.setattr(
        storage,
        "save",
        lambda tabs, active_tab=0, path=data_file: real_save(tabs, active_tab, path),
    )

    # Each test spins up its own Tk interpreter plus a background Win32 hook
    # thread (WindowEventListener) that outlives root.destroy() by a beat -
    # there's no explicit stop(). Creating the next interpreter while that
    # thread is still unwinding occasionally raises a spurious TclError from
    # Tcl's own init, unrelated to anything under test. Retrying past that
    # transient window is simpler than adding a stop() path that production
    # code, which lives for the process lifetime, has never needed.
    ov = None
    last_exc = None
    for _ in range(5):
        try:
            ov = TerminalOverlay()
            break
        except tk.TclError as exc:
            last_exc = exc
            time.sleep(0.15)
    if ov is None:
        raise last_exc

    ov.root.deiconify()
    yield ov
    ov.root.destroy()


def _add(overlay, text):
    overlay.entry.insert(0, text)
    overlay.add_todo()


# --------------------------------------------------------------- basic todos


def test_starts_with_one_default_tab(overlay):
    assert len(overlay.tabs) == 1
    assert overlay.tabs[0]["name"] == "Tab 1"
    assert overlay.todos == []


def test_add_and_reorder_todos(overlay):
    for text in ["first", "second", "third"]:
        _add(overlay, text)
    assert [t["text"] for t in overlay.todos] == ["first", "second", "third"]

    # Drag row 0 down to row 2, the way _on_list_drag moves an item.
    item = overlay.todos.pop(0)
    overlay.todos.insert(2, item)
    overlay.refresh_list()
    assert [t["text"] for t in overlay.todos] == ["second", "third", "first"]


def test_edit_todo_in_place(overlay):
    _add(overlay, "fix the bug")
    overlay.listbox.selection_set(0)

    overlay.start_edit_todo()
    assert overlay._entry_mode == "edit_todo"
    assert overlay.entry.get() == "fix the bug"

    overlay.entry.delete(0, "end")
    overlay.entry.insert(0, "fix the login bug")
    overlay._on_entry_return()

    assert overlay.todos[0]["text"] == "fix the login bug"
    assert overlay._entry_mode == "todo"
    assert overlay._edit_index is None
    assert overlay.listbox.curselection() == (0,)


def test_edit_todo_escape_cancels_without_saving(overlay):
    _add(overlay, "original")
    overlay.listbox.selection_set(0)
    overlay.start_edit_todo()
    overlay.entry.delete(0, "end")
    overlay.entry.insert(0, "should not save")
    overlay._on_entry_escape()
    assert overlay.todos[0]["text"] == "original"
    assert overlay._entry_mode == "todo"


def test_edit_todo_empty_text_is_a_no_op(overlay):
    _add(overlay, "keep me")
    overlay.listbox.selection_set(0)
    overlay.start_edit_todo()
    overlay.entry.delete(0, "end")
    overlay._on_entry_return()
    assert overlay.todos[0]["text"] == "keep me"


def test_delete_and_undo_restores_it(overlay):
    for text in ["alpha", "beta", "gamma"]:
        _add(overlay, text)

    overlay.listbox.selection_set(1)
    overlay.remove_todo()
    assert [t["text"] for t in overlay.todos] == ["alpha", "gamma"]

    overlay.undo()
    assert [t["text"] for t in overlay.todos] == ["alpha", "beta", "gamma"]


def test_clear_done_and_undo_restores_all(overlay):
    _add(overlay, "keep")
    _add(overlay, "done one")
    _add(overlay, "done two")
    overlay.todos[1]["done"] = True
    overlay.todos[2]["done"] = True

    overlay.clear_done()
    assert [t["text"] for t in overlay.todos] == ["keep"]

    overlay.undo()
    assert [t["text"] for t in overlay.todos] == ["keep", "done one", "done two"]


# -------------------------------------------------------------------- tabs


def test_new_tab_flow(overlay):
    overlay.start_new_tab()
    assert overlay._entry_mode == "new_tab"
    assert overlay.entry.get() == "Tab 2"  # default name, pre-selected

    overlay.entry.delete(0, "end")
    overlay.entry.insert(0, "Work")
    overlay._on_entry_return()

    assert len(overlay.tabs) == 2
    assert overlay.active_tab == 1
    assert overlay.tabs[1]["name"] == "Work"
    assert overlay.todos == []
    assert overlay.tab_label.cget("text") == "Work"


def test_rename_tab(overlay):
    overlay.start_rename_tab()
    assert overlay.entry.get() == "Tab 1"
    overlay.entry.delete(0, "end")
    overlay.entry.insert(0, "Personal")
    overlay._on_entry_return()
    assert overlay.tabs[0]["name"] == "Personal"
    assert overlay.tab_label.cget("text") == "Personal"


def test_switch_tab_preserves_each_tabs_todos(overlay):
    _add(overlay, "tab1 item")
    overlay.start_new_tab()
    overlay._on_entry_return()
    _add(overlay, "tab2 item")

    overlay._switch_tab(0)
    assert [t["text"] for t in overlay.todos] == ["tab1 item"]
    overlay._switch_tab(1)
    assert [t["text"] for t in overlay.todos] == ["tab2 item"]


def test_new_tab_is_capped_at_max_tabs(overlay):
    while len(overlay.tabs) < storage.MAX_TABS:
        overlay.start_new_tab()
        overlay._on_entry_return()
    assert len(overlay.tabs) == storage.MAX_TABS

    overlay.start_new_tab()
    assert len(overlay.tabs) == storage.MAX_TABS
    assert overlay._entry_mode == "todo"


def test_delete_tab_prunes_undo_entries_for_it(overlay):
    overlay.start_new_tab()
    overlay._on_entry_return()
    _add(overlay, "tab2 item")
    overlay.listbox.selection_set(0)
    overlay.remove_todo()  # undo entry for tab 1

    overlay._switch_tab(0)
    _add(overlay, "tab0 item")
    overlay.listbox.selection_set(0)
    overlay.remove_todo()  # undo entry for tab 0

    assert {tab for tab, _ in overlay._undo_stack} == {0, 1}

    overlay._switch_tab(1)
    overlay._delete_tab(1)

    assert len(overlay.tabs) == 1
    assert all(tab == 0 for tab, _ in overlay._undo_stack)
    overlay.undo()
    assert overlay.todos[0]["text"] == "tab0 item"


def test_cannot_delete_the_last_tab(overlay):
    overlay._delete_tab(0)
    assert len(overlay.tabs) == 1


def test_five_tab_switcher_does_not_overlap_title(overlay):
    """The tab-number buttons live left of the centred "Sidenote" title; past
    5 tabs the row can reach far enough right to collide with it (a real bug
    caught once already - see AGENTS.md's MAX_TABS note)."""
    while len(overlay.tabs) < storage.MAX_TABS:
        overlay.start_new_tab()
        overlay._on_entry_return()

    overlay.root.update_idletasks()
    drag_bar = overlay.add_tab_btn.master
    title = next(
        w
        for w in drag_bar.winfo_children()
        if w
        not in (
            overlay.add_tab_btn,
            overlay.tabs_frame,
            overlay.help_btn,
            overlay.lock_btn,
        )
    )
    tabs_frame_right = overlay.tabs_frame.winfo_x() + overlay.tabs_frame.winfo_width()
    assert tabs_frame_right <= title.winfo_x()


def test_header_button_order(overlay):
    """+ sits left of the tab switcher; ? sits left of the lock button."""
    overlay.root.update_idletasks()
    assert overlay.add_tab_btn.winfo_x() < overlay.tabs_frame.winfo_x()
    assert overlay.help_btn.winfo_x() < overlay.lock_btn.winfo_x()


# --------------------------------------------------------------- persistence


def test_save_and_reload_round_trips_tabs_and_todos(overlay):
    _add(overlay, "tab1 item")
    overlay.start_new_tab()
    overlay._on_entry_return()
    overlay.tabs[1]["name"] = "Work"
    _add(overlay, "tab2 item")
    overlay.save_todos()

    tabs, active, error = storage.load()
    assert error is None
    assert active == 1
    assert [t["name"] for t in tabs] == ["Tab 1", "Work"]
    assert tabs[0]["todos"][0]["text"] == "tab1 item"
    assert tabs[1]["todos"][0]["text"] == "tab2 item"


# ---------------------------------------------------------------- real events


def test_real_click_selects_a_row_alongside_drag_bindings(overlay):
    """The drag-to-reorder bindings on <Button-1> must not break the
    Listbox's own click-to-select behavior."""
    for text in ["alpha", "beta"]:
        _add(overlay, text)
    overlay.root.update_idletasks()

    bbox = overlay.listbox.bbox(0)
    y = bbox[1] + bbox[3] // 2
    overlay.listbox.event_generate("<Button-1>", x=5, y=y)
    overlay.listbox.event_generate("<ButtonRelease-1>", x=5, y=y)
    overlay.root.update()

    assert overlay.listbox.curselection() == (0,)
