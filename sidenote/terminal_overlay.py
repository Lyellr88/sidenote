#!/usr/bin/env python3
"""
Terminal Todo Overlay - a todo list that attaches itself to your terminal window.

Threading note: tkinter is not thread-safe. Window events arrive on a Win32 hook
thread and the global hotkey arrives on the ``keyboard`` library's thread, so
neither is allowed to touch a widget directly. Both push callables onto
``self._work`` and the main thread drains that queue from a tk ``after`` pump.

This class is split across overlay_ui.py, overlay_positioning.py,
overlay_tabs.py, and overlay_todos.py as mixins - see AGENTS.md's "Module
Split" section for what lives where and why. This file keeps the pieces that
tie them together: setup, cross-thread plumbing, the shared entry-field state
machine (naming a tab and editing a todo both drive it), visibility, and the
process lifecycle.
"""

import contextlib
import os
import queue
import sys
import threading
import tkinter as tk

from . import storage, winutil
from .lockfile import SingleInstance
from .overlay_positioning import PositioningMixin
from .overlay_tabs import TabsMixin
from .overlay_theme import ACCENT, PUMP_MS
from .overlay_todos import TodosMixin
from .overlay_ui import OverlayUIMixin


class TerminalOverlay(OverlayUIMixin, PositioningMixin, TabsMixin, TodosMixin):
    def __init__(self):
        self.root = tk.Tk()
        self.visible = False
        self.tabs = [storage.new_tab()]
        self.active_tab = 0
        self.todos = self.tabs[0]["todos"]
        self.locked_terminal = None
        self.is_locked = False
        self.follow_terminal = True
        self.user_hidden = False
        self.own_pid = os.getpid()
        self.instance = None

        self._work = queue.Queue()
        self._terminal = None
        self._moving = False
        self._reposition_job = None
        self._help_window = None
        self._lock_tooltip = None
        self._confirm_window = None
        self._scale = 1.0
        self._user_width = None
        self._applied_w = None
        # "todo" | "new_tab" | "rename_tab" | "edit_todo" - what Enter in the
        # entry field does.
        self._entry_mode = "todo"
        self._edit_index = None
        self._undo_stack = []
        self._drag_from = None

        self.setup_window()
        self.setup_ui()
        self.load_todos()

        self._pump()
        self._start_listener()
        self._fallback_poll()

    # ------------------------------------------------- cross-thread machinery

    def _post(self, fn):
        """Queue work for the main thread. Safe to call from any thread."""
        self._work.put(fn)

    def _pump(self):
        """Drain queued work on the main thread, then reschedule."""
        try:
            while True:
                fn = self._work.get_nowait()
                # fn is an arbitrary queued callback (from the Win32 hook
                # thread or the hotkey thread); one bad callback must not
                # take down the pump that every other queued callback relies
                # on, so this stays broad rather than narrowed to a guess.
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    self.set_status(f"Error: {exc}", error=True)
        except queue.Empty:
            pass
        self.root.after(PUMP_MS, self._pump)

    # ------------------------------------------------------- entry field mode

    def _prime_entry(self, text):
        """Load the entry field for a naming or editing step and flag it
        visually. Shared by tab naming/renaming and todo editing."""
        self.entry.delete(0, tk.END)
        self.entry.insert(0, text)
        self.entry.select_range(0, tk.END)
        self.entry.icursor(tk.END)
        self.entry.config(
            highlightthickness=2, highlightbackground=ACCENT, highlightcolor=ACCENT
        )
        self.entry.focus_set()

    def _leave_entry_mode(self):
        self._entry_mode = "todo"
        self._edit_index = None
        self.entry.delete(0, tk.END)
        self.entry.config(highlightthickness=0)

    def _on_entry_return(self, event=None):
        if self._entry_mode == "new_tab":
            self._commit_new_tab()
        elif self._entry_mode == "rename_tab":
            self._commit_rename_tab()
        elif self._entry_mode == "edit_todo":
            self._commit_edit_todo()
        else:
            self.add_todo()

    def _on_entry_escape(self, event=None):
        if self._entry_mode != "todo":
            self._leave_entry_mode()
            self.update_counts()
        else:
            self.hide()

    # ------------------------------------------------------------- visibility

    def show(self):
        self.user_hidden = False
        if self.follow_terminal:
            self.position_next_to_terminal()
        self.root.deiconify()
        self.root.lift()
        self.entry.focus_set()
        self.visible = True

    def hide(self):
        self.hide_help()
        self._hide_confirm()
        self.root.withdraw()
        self.visible = False
        self.user_hidden = True

    def toggle(self):
        if self.visible:
            self.hide()
        else:
            self.show()

    def on_closing(self):
        self.save_todos()
        if self.instance:
            self.instance.release()
        self.root.quit()
        self.root.destroy()

    # -------------------------------------------------------------------- run

    def setup_hotkey(self):
        def hotkey_thread():
            try:
                import keyboard

                # The callback runs on the keyboard library's thread, so hand
                # the toggle back to the main thread rather than calling it here.
                keyboard.add_hotkey(
                    "shift+tab", lambda: self._post(self.toggle), suppress=False
                )
                keyboard.wait()
            # The keyboard library's failure modes vary by OS and permission
            # level (missing native module, no root on Linux, etc.) - the
            # goal here is "report it and keep running" for any of them
            # rather than let this background thread die silently.
            except Exception as exc:  # noqa: BLE001
                message = f"Hotkey unavailable: {exc}"
                self._post(lambda: self.set_status(message, error=True))

        threading.Thread(target=hotkey_thread, daemon=True).start()

    def run(self, instance=None):
        self.instance = instance
        self.setup_hotkey()

        if "--show" in sys.argv:
            self.show()

        with contextlib.suppress(KeyboardInterrupt):
            self.root.mainloop()


def main():
    winutil.enable_dpi_awareness()  # must run before Tk creates any window

    instance = SingleInstance()
    with instance as can_run:
        if not can_run:
            print("Terminal overlay is already running!")
            print("Press Shift+Tab to toggle the existing instance")
            return 0

        TerminalOverlay().run(instance)
    return 0


if __name__ == "__main__":
    sys.exit(main())
