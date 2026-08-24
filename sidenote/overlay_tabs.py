"""Tab management: creating, naming, switching, and deleting tabs. Naming and
renaming go through the shared entry-field state machine in terminal_overlay.py
(_prime_entry / _leave_entry_mode) - the same mechanism todo editing uses.
"""

import tkinter as tk

from . import storage
from .overlay_theme import BAR_BG, FG, MUTED, SELECT_BG


class TabsMixin:
    def start_new_tab(self):
        if len(self.tabs) >= storage.MAX_TABS:
            self.set_status(f"Max {storage.MAX_TABS} tabs", error=True)
            return
        self._entry_mode = "new_tab"
        self._prime_entry(f"Tab {len(self.tabs) + 1}")
        self.set_status("Name the tab, Enter to create")

    def start_rename_tab(self):
        self._entry_mode = "rename_tab"
        self._prime_entry(self.tabs[self.active_tab]["name"])
        self.set_status("Rename tab, Enter to save")

    def _commit_new_tab(self):
        name = self.entry.get().strip() or f"Tab {len(self.tabs) + 1}"
        self.tabs.append(storage.new_tab(name))
        self._leave_entry_mode()
        self._switch_tab(len(self.tabs) - 1)
        self.save_todos()

    def _commit_rename_tab(self):
        name = self.entry.get().strip()
        if name:
            self.tabs[self.active_tab]["name"] = name
            self.save_todos()
        self._leave_entry_mode()
        self._update_tab_label()

    def _switch_tab(self, index):
        self.active_tab = index
        self.todos = self.tabs[index]["todos"]
        self.refresh_list()
        self._update_tab_label()
        self._render_tabs()

    def _update_tab_label(self):
        self.tab_label.config(text=self.tabs[self.active_tab]["name"])
        if len(self.tabs) > 1:
            self.delete_tab_btn.pack(side=tk.LEFT, fill=tk.Y, after=self.tab_label)
        else:
            self.delete_tab_btn.pack_forget()

    def _render_tabs(self):
        """Numbered switcher buttons, shown only once a second tab exists."""
        for child in self.tabs_frame.winfo_children():
            child.destroy()
        if len(self.tabs) <= 1:
            return
        for i in range(len(self.tabs)):
            active = i == self.active_tab
            btn = tk.Label(
                self.tabs_frame,
                text=str(i + 1),
                bg=SELECT_BG if active else BAR_BG,
                fg=FG if active else MUTED,
                cursor="hand2",
                # Tight padding: at 5 tabs this row sits right next to the
                # centred title, and any wider risks overlapping it.
                font=("Consolas", 8, "bold" if active else "normal"),
                padx=2,
            )
            btn.pack(side=tk.LEFT)
            btn.bind("<Button-1>", lambda e, idx=i: self._switch_tab(idx))

    def _confirm_delete_tab(self):
        if len(self.tabs) <= 1:
            return
        index = self.active_tab
        name = self.tabs[index]["name"]
        count = len(self.tabs[index]["todos"])
        if count == 0:
            detail = "It's empty."
        elif count == 1:
            detail = "1 todo goes with it."
        else:
            detail = f"{count} todos go with it."
        self._show_confirm(
            f'Delete "{name}"? {detail}',
            lambda: self._delete_tab(index),
            self.delete_tab_btn,
        )

    def _delete_tab(self, index):
        if len(self.tabs) <= 1 or not (0 <= index < len(self.tabs)):
            return
        del self.tabs[index]
        # Undo entries point at a tab by index; the deleted tab's entries no
        # longer have anywhere to go, and later tabs shift down by one.
        self._undo_stack = [
            (i - 1 if i > index else i, snapshot)
            for i, snapshot in self._undo_stack
            if i != index
        ]
        self._switch_tab(min(index, len(self.tabs) - 1))
        self.save_todos()
        self.set_status("Tab deleted")
