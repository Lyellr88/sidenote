"""Todo list operations: add, edit, check off, remove, reorder, undo, copy,
and the listbox rendering / persistence that back them.
"""

import tkinter as tk

from . import storage
from .overlay_theme import COPY_FLASH, COPY_FLASH_MS, DONE_FG, ERROR_FG, FG, MUTED


class TodosMixin:
    def _on_mousewheel(self, event):
        self.listbox.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def copy_todo(self, event=None):
        index = self._selected_index(event)
        if index is None:
            return "break"
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.todos[index].get("text", ""))
        except tk.TclError as exc:
            self.set_status(f"Copy failed: {exc}", error=True)
            return "break"
        self.set_status("Copied")
        self._flash_row(index)
        return "break"

    def _flash_row(self, index):
        """Fade the copied row back to its normal colour.

        Stepping through a few shades reads as an acknowledgement; a single
        on/off blink at this size just looks like a rendering glitch.
        """

        def step(i):
            if index >= len(self.todos) or index >= self.listbox.size():
                return
            if i < len(COPY_FLASH):
                colour = COPY_FLASH[i]
            else:
                colour = DONE_FG if self.todos[index].get("done") else FG
            try:
                # selectforeground too, or the flash is invisible on the
                # selected row: Tk draws that one with the select colour.
                self.listbox.itemconfig(index, fg=colour, selectforeground=colour)
            except tk.TclError:
                return
            if i < len(COPY_FLASH):
                self.root.after(COPY_FLASH_MS, lambda: step(i + 1))

        step(0)

    def add_todo(self, event=None):
        text = self.entry.get().strip()
        if not text:
            return
        self.todos.append(storage.new_todo(text))
        self.entry.delete(0, tk.END)
        self.refresh_list()
        self.listbox.see(tk.END)
        self.save_todos()

    def start_edit_todo(self, event=None):
        index = self._selected_index(event)
        if index is None:
            return "break"
        self._entry_mode = "edit_todo"
        self._edit_index = index
        self._prime_entry(self.todos[index].get("text", ""))
        self.set_status("Edit todo, Enter to save")
        return "break"

    def _commit_edit_todo(self):
        text = self.entry.get().strip()
        index = self._edit_index
        self._leave_entry_mode()
        if text and index is not None and index < len(self.todos):
            self.todos[index]["text"] = text
            self.refresh_list()
            self.listbox.selection_set(index)
            self.listbox.activate(index)
            self.save_todos()

    def toggle_done(self, event=None):
        index = self._selected_index(event)
        if index is None:
            return "break"
        self.todos[index]["done"] = not self.todos[index].get("done", False)
        self.refresh_list()
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.save_todos()
        return "break"

    def remove_todo(self, event=None):
        index = self._selected_index(event)
        if index is None:
            return "break"
        self._push_undo()
        del self.todos[index]
        self.refresh_list()
        if self.todos:
            self.listbox.selection_set(min(index, len(self.todos) - 1))
        self.save_todos()
        return "break"

    def clear_done(self, event=None):
        remaining = [t for t in self.todos if not t.get("done")]
        removed = len(self.todos) - len(remaining)
        if not removed:
            self.set_status("Nothing checked off yet")
            return "break"
        self._push_undo()
        # Slice-assign, not rebind: self.todos is the same list object as
        # self.tabs[self.active_tab]["todos"], and a plain `self.todos = ...`
        # would break that alias.
        self.todos[:] = remaining
        self.refresh_list()
        self.save_todos()
        self.set_status(f"Cleared {removed} done")
        return "break"

    def _push_undo(self, limit=10):
        """Snapshot the active tab's list before a destructive change."""
        snapshot = [dict(t) for t in self.todos]
        self._undo_stack.append((self.active_tab, snapshot))
        del self._undo_stack[:-limit]

    def undo(self, event=None):
        if not self._undo_stack:
            self.set_status("Nothing to undo")
            return "break"
        tab_index, snapshot = self._undo_stack.pop()
        self.tabs[tab_index]["todos"][:] = snapshot
        if tab_index == self.active_tab:
            self.refresh_list()
        self.save_todos()
        self.set_status("Restored")
        return "break"

    def _on_list_press(self, event):
        index = self.listbox.nearest(event.y)
        self._drag_from = index if 0 <= index < len(self.todos) else None

    def _on_list_drag(self, event):
        if self._drag_from is None:
            return
        target = self.listbox.nearest(event.y)
        if target < 0 or target >= len(self.todos) or target == self._drag_from:
            return
        item = self.todos.pop(self._drag_from)
        self.todos.insert(target, item)
        self.refresh_list()
        self.listbox.selection_set(target)
        self.listbox.activate(target)
        self._drag_from = target

    def _on_list_release(self, event):
        if self._drag_from is not None:
            self.save_todos()
        self._drag_from = None

    def _selected_index(self, event=None):
        """Index under the pointer for mouse events, else the selected row."""
        if event is not None and getattr(event, "num", None) in (1, 3):
            index = self.listbox.nearest(event.y)
            if index < 0 or index >= len(self.todos):
                return None
            # nearest() clamps to the closest row, so reject clicks below the
            # last item instead of toggling whatever happens to be at the end.
            bbox = self.listbox.bbox(index)
            if not bbox or event.y > bbox[1] + bbox[3]:
                return None
            return index

        selection = self.listbox.curselection()
        if not selection:
            return None
        index = selection[0]
        return index if index < len(self.todos) else None

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        for i, todo in enumerate(self.todos):
            self.listbox.insert(tk.END, storage.display(todo))
            if todo.get("done"):
                self.listbox.itemconfig(i, fg=DONE_FG, selectforeground=DONE_FG)
        self.update_counts()

    def update_counts(self):
        done = sum(1 for t in self.todos if t.get("done"))
        open_count = len(self.todos) - done
        if not self.todos:
            self.set_status("No todos yet - type above")
        else:
            self.set_status(f"{open_count} open · {done} done")

    def set_status(self, message, error=False):
        self.status.config(text=message, fg=ERROR_FG if error else MUTED)

    def save_todos(self):
        error = storage.save(self.tabs, self.active_tab)
        if error:
            # Previously swallowed: a full or read-only disk meant todos stopped
            # persisting with no sign of it until a restart lost them.
            self.set_status(error, error=True)
        else:
            self.update_counts()

    def load_todos(self):
        self.tabs, self.active_tab, error = storage.load()
        self.todos = self.tabs[self.active_tab]["todos"]
        self.refresh_list()
        self._update_tab_label()
        self._render_tabs()
        if error:
            self.set_status(error, error=True)
