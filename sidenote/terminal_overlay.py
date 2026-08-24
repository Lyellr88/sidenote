#!/usr/bin/env python3
"""
Terminal Todo Overlay - a todo list that attaches itself to your terminal window.

Threading note: tkinter is not thread-safe. Window events arrive on a Win32 hook
thread and the global hotkey arrives on the ``keyboard`` library's thread, so
neither is allowed to touch a widget directly. Both push callables onto
``self._work`` and the main thread drains that queue from a tk ``after`` pump.
"""

import os
import queue
import sys
import threading
import tkinter as tk

from . import storage, winutil
from .lockfile import SingleInstance

BG = "#1e1e1e"
BAR_BG = "#2d2d30"
LIST_BG = "#252526"
SELECT_BG = "#2f3033"
FG = "#cccccc"
MUTED = "#858585"
DONE_FG = "#6a6a6a"
ERROR_FG = "#f48771"
LOCKED_BG = "#8b0000"
ACCENT = "#60a5fa"

BASE_WIDTH = 280
PUMP_MS = 40
FALLBACK_POLL_MS = 2000
REPOSITION_DEBOUNCE_MS = 60

COPY_FLASH = ["#4ec9b0", "#3f9c88", "#317a6c"]
COPY_FLASH_MS = 70

HELP_ROWS = [
    ("Shift+Tab", "Toggle overlay (works anywhere)"),
    ("Enter", "Add todo"),
    ("Double-click", "Check off / uncheck a todo"),
    ("Right-click", "Copy a todo's text"),
    ("Drag a todo", "Reorder it in the list"),
    ("Space", "Check off / uncheck selection"),
    ("Delete", "Remove selected todo"),
    ("Ctrl+Delete", "Clear all checked-off todos"),
    ("Ctrl+Z", "Undo the last delete"),
    ("+ button", "Add a tab (up to 5)"),
    ("Double-click tab name", "Rename the current tab"),
    ("× next to tab name", "Delete the current tab, with confirmation"),
    ("Escape", "Hide overlay"),
    ("Lock button", "Stick to one specific terminal"),
    ("Drag title bar", "Detach and place it yourself"),
]


class TerminalOverlay:
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
        self._entry_mode = "todo"
        self._undo_stack = []
        self._drag_from = None

        self.setup_window()
        self.setup_ui()
        self.load_todos()

        self._pump()
        self._start_listener()
        self._fallback_poll()

    # ------------------------------------------------------------------ setup

    def setup_window(self):
        self.root.title("")
        self.root.geometry(f"{BASE_WIDTH}x600+100+100")
        self.root.configure(bg=BG)
        self.root.withdraw()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.bind("<Configure>", self._on_configure)

    def setup_ui(self):
        drag_bar = tk.Frame(self.root, bg=BAR_BG, height=25, cursor="fleur")
        drag_bar.pack(fill=tk.X)
        drag_bar.pack_propagate(False)

        self.add_tab_btn = tk.Label(
            drag_bar,
            text="+",
            bg=BAR_BG,
            fg=FG,
            cursor="hand2",
            font=("Consolas", 10, "bold"),
            padx=6,
        )
        self.add_tab_btn.pack(side=tk.LEFT)
        self.add_tab_btn.bind("<Button-1>", lambda e: self.start_new_tab())

        self.tabs_frame = tk.Frame(drag_bar, bg=BAR_BG)
        self.tabs_frame.pack(side=tk.LEFT)

        self.lock_btn = tk.Label(
            drag_bar,
            text="\U0001f513",
            bg=BAR_BG,
            fg="white",
            cursor="hand2",
            font=("Segoe UI", 11),
            padx=5,
            pady=2,
        )
        self.lock_btn.pack(side=tk.RIGHT, padx=2)
        self.lock_btn.bind("<Button-1>", lambda e: self.toggle_lock())
        self.lock_btn.bind("<Enter>", self.show_lock_tooltip)
        self.lock_btn.bind("<Leave>", self.hide_lock_tooltip)

        self.help_btn = tk.Label(
            drag_bar,
            text="?",
            bg=BAR_BG,
            fg=FG,
            cursor="hand2",
            font=("Consolas", 10, "bold"),
            padx=6,
        )
        self.help_btn.pack(side=tk.RIGHT)
        self.help_btn.bind("<Button-1>", lambda e: self.toggle_help())

        title = tk.Label(
            drag_bar,
            text="Sidenote",
            fg=FG,
            bg=BAR_BG,
            font=("Consolas", 9),
            cursor="fleur",
        )
        title.place(relx=0.5, rely=0.5, anchor="center")

        for widget in (drag_bar, title):
            widget.bind("<Button-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.on_drag)

        input_frame = tk.Frame(self.root, bg=BG)
        input_frame.pack(fill=tk.X, padx=8, pady=8)

        self.entry = tk.Entry(
            input_frame,
            bg="#3e3e42",
            fg="white",
            insertbackground="white",
            relief="flat",
            font=("Consolas", 10),
            bd=5,
            highlightthickness=0,
        )
        self.entry.pack(fill=tk.X)
        self.entry.bind("<Return>", self._on_entry_return)
        self.entry.bind("<Escape>", self._on_entry_escape)

        list_container = tk.Frame(self.root, bg=BG)
        list_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=0)

        self.listbox = tk.Listbox(
            list_container,
            bg=LIST_BG,
            fg=FG,
            selectbackground=SELECT_BG,
            selectforeground="",
            relief="flat",
            font=("Consolas", 9),
            bd=0,
            highlightthickness=0,
            activestyle="none",
        )
        self.listbox.pack(fill=tk.BOTH, expand=True)

        self.listbox.bind("<MouseWheel>", self._on_mousewheel)
        self.listbox.bind("<Button-3>", self.copy_todo)
        self.listbox.bind("<Double-Button-1>", self.toggle_done)
        self.listbox.bind("<space>", self.toggle_done)
        self.listbox.bind("<Delete>", self.remove_todo)
        self.listbox.bind("<BackSpace>", self.remove_todo)
        self.listbox.bind("<Control-Delete>", self.clear_done)
        self.listbox.bind("<Escape>", lambda e: self.hide())

        self.listbox.bind("<Button-1>", self._on_list_press)
        self.listbox.bind("<B1-Motion>", self._on_list_drag)
        self.listbox.bind("<ButtonRelease-1>", self._on_list_release)

        self.root.bind_all("<Control-z>", self.undo)

        footer = tk.Frame(self.root, bg=BAR_BG, height=30)
        footer.pack(fill=tk.X)
        footer.pack_propagate(False)

        self.tab_label = tk.Label(
            footer,
            text="",
            fg=MUTED,
            bg=BAR_BG,
            font=("Consolas", 8),
            anchor="w",
            cursor="hand2",
            padx=8,
        )
        self.tab_label.pack(side=tk.LEFT, fill=tk.Y)
        self.tab_label.bind("<Double-Button-1>", lambda e: self.start_rename_tab())

        self.delete_tab_btn = tk.Label(
            footer, text="×", fg=MUTED, bg=BAR_BG, cursor="hand2", font=("Consolas", 10)
        )
        self.delete_tab_btn.bind("<Button-1>", lambda e: self._confirm_delete_tab())

        self.status = tk.Label(
            footer,
            text="",
            fg=MUTED,
            bg=BAR_BG,
            font=("Consolas", 8),
            anchor="e",
            padx=8,
        )
        self.status.pack(side=tk.RIGHT, fill=tk.Y)

        self.drag_start_x = 0
        self.drag_start_y = 0

    # ------------------------------------------------- cross-thread machinery

    def _post(self, fn):
        """Queue work for the main thread. Safe to call from any thread."""
        self._work.put(fn)

    def _pump(self):
        """Drain queued work on the main thread, then reschedule."""
        try:
            while True:
                fn = self._work.get_nowait()
                try:
                    fn()
                except Exception as exc:
                    self.set_status(f"Error: {exc}", error=True)
        except queue.Empty:
            pass
        self.root.after(PUMP_MS, self._pump)

    def _start_listener(self):
        self._listener = winutil.WindowEventListener(self._on_window_event)
        self._listener.start()

    def _on_window_event(self, event, hwnd):
        """Runs on the Win32 hook thread - queue only, never touch widgets."""
        if event == winutil.EVENT_SYSTEM_FOREGROUND:
            self._post(lambda: self._handle_foreground(hwnd))
        elif event == winutil.EVENT_SYSTEM_MOVESIZESTART:
            self._post(lambda: self._handle_move_start(hwnd))
        elif event == winutil.EVENT_SYSTEM_MOVESIZEEND:
            self._post(lambda: self._handle_move_end(hwnd))
        elif event == winutil.EVENT_OBJECT_LOCATIONCHANGE:
            self._post(lambda: self._handle_location_change(hwnd))
        elif event == winutil.EVENT_SYSTEM_MINIMIZESTART:
            self._post(lambda: self._handle_minimize(hwnd, True))
        elif event == winutil.EVENT_SYSTEM_MINIMIZEEND:
            self._post(lambda: self._handle_minimize(hwnd, False))
        elif event == winutil.EVENT_OBJECT_DESTROY:
            self._post(lambda: self._handle_destroy(hwnd))

    # --------------------------------------------------------- event handlers

    def _handle_foreground(self, hwnd):
        if not self._is_current_terminal(hwnd):
            return
        self._terminal = hwnd
        if self.visible and not self._moving:
            # Raise without taking focus, so typing keeps going to the terminal.
            own = self._own_hwnd()
            if own:
                winutil.bring_to_front(own)

    def _handle_move_start(self, hwnd):
        if not self._is_current_terminal(hwnd):
            return
        self._moving = True
        if self.visible and self.follow_terminal:
            self.root.withdraw()

    def _handle_move_end(self, hwnd):
        if not self._is_current_terminal(hwnd):
            return
        self._moving = False
        if self.visible and self.follow_terminal:
            self.position_next_to_terminal()
            self.root.deiconify()

    def _handle_location_change(self, hwnd):
        """Snap, maximise, and restore land here rather than in move/size."""
        if self._moving or not self._is_current_terminal(hwnd):
            return
        if not (self.visible and self.follow_terminal):
            return
        # Coalesce the burst of events a single resize produces.
        if self._reposition_job is not None:
            self.root.after_cancel(self._reposition_job)
        self._reposition_job = self.root.after(
            REPOSITION_DEBOUNCE_MS, self._run_reposition
        )

    def _run_reposition(self):
        self._reposition_job = None
        self.position_next_to_terminal()

    def _handle_minimize(self, hwnd, minimized):
        if not self._is_current_terminal(hwnd) or not self.visible:
            return
        if minimized:
            self.root.withdraw()
        elif self.follow_terminal:
            self.position_next_to_terminal()
            self.root.deiconify()

    def _handle_destroy(self, hwnd):
        if hwnd == self.locked_terminal:
            self._release_lock()
        if hwnd == self._terminal:
            self._terminal = None

    def _fallback_poll(self):
        """Catch terminals opening/closing, which produce no hook event we track.

        Cheap: once every couple of seconds, versus the old 10x/second EnumWindows.
        """
        terminal = self.get_terminal_window()
        if terminal and not self.visible and not self.user_hidden:
            self.show()
        elif terminal and self.visible and self.follow_terminal and not self._moving:
            self.position_next_to_terminal()
        elif not terminal and self.visible:
            self.root.withdraw()
            self.visible = False
        self.root.after(FALLBACK_POLL_MS, self._fallback_poll)

    # ------------------------------------------------------ window management

    def _own_hwnd(self):
        try:
            return int(self.root.wm_frame(), 16)
        except (ValueError, tk.TclError):
            return None

    def _is_current_terminal(self, hwnd):
        if self.is_locked:
            return hwnd == self.locked_terminal
        if hwnd == self._terminal:
            return True
        return winutil.is_terminal(hwnd, self.own_pid)

    def get_terminal_window(self):
        if self.is_locked and self.locked_terminal:
            if winutil.is_terminal(self.locked_terminal, self.own_pid):
                return self.locked_terminal
            self._release_lock()

        if self._terminal and winutil.is_terminal(self._terminal, self.own_pid):
            return self._terminal

        self._terminal = winutil.find_terminal(self.own_pid)
        return self._terminal

    def position_next_to_terminal(self):
        terminal = self.get_terminal_window()
        if not terminal:
            return
        try:
            _, term_top, term_right, term_bottom = winutil.visible_rect(terminal)
        except Exception as exc:
            self.set_status(f"Positioning failed: {exc}", error=True)
            return

        own = self._own_hwnd()
        offset_x, offset_y, chrome_w, chrome_h = (
            winutil.window_metrics(own) if own else (0, 0, 0, 0)
        )

        self._apply_scaling(winutil.dpi_for_window(terminal))

        if self._user_width:
            client_w = max(120, self._user_width)
        else:
            client_w = max(120, int(BASE_WIDTH * self._scale) - chrome_w)
        client_h = max(120, (term_bottom - term_top) - chrome_h)
        self.root.geometry(
            f"{client_w}x{client_h}+{term_right - offset_x}+{term_top - offset_y}"
        )
        self._applied_w = client_w

    def _on_configure(self, event):
        """Remember a width the user set by dragging the window edge.

        Every terminal event re-runs position_next_to_terminal, which would
        otherwise snap a widened overlay straight back to BASE_WIDTH. Widths we
        applied ourselves are recorded in _applied_w, so anything that differs
        came from the user.
        """
        if event.widget is not self.root or self._applied_w is None:
            return
        if event.width != self._applied_w:
            self._user_width = event.width
            self._applied_w = event.width

    def _apply_scaling(self, dpi):
        scale = dpi / 96.0
        if abs(scale - self._scale) < 0.01:
            return
        self._scale = scale
        try:
            self.root.tk.call("tk", "scaling", dpi / 72.0)
        except tk.TclError:
            pass

    def start_drag(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.follow_terminal = False  # manual placement wins over auto-follow
        self.set_status("Detached - lock to re-attach")

    def on_drag(self, event):
        x = self.root.winfo_x() + (event.x - self.drag_start_x)
        y = self.root.winfo_y() + (event.y - self.drag_start_y)
        self.root.geometry(f"+{x}+{y}")

    def toggle_lock(self):
        if self.is_locked:
            self._release_lock()
            return

        terminal = winutil.find_terminal(self.own_pid)
        if not terminal:
            self.set_status("No terminal found to lock to", error=True)
            return

        self.is_locked = True
        self.locked_terminal = terminal
        self.follow_terminal = True
        self.lock_btn.config(text="\U0001f512", bg=LOCKED_BG)
        self.position_next_to_terminal()

    def _release_lock(self):
        self.is_locked = False
        self.locked_terminal = None
        self.lock_btn.config(text="\U0001f513", bg=BAR_BG)

    # --------------------------------------------------------------- tooltips

    def show_lock_tooltip(self, event):
        text = (
            "Locked to terminal" if self.is_locked else "Click to lock to this terminal"
        )
        self.hide_lock_tooltip()
        self._lock_tooltip = tk.Toplevel(self.root)
        self._lock_tooltip.wm_overrideredirect(True)
        self._lock_tooltip.wm_geometry(f"+{event.x_root + 10}+{event.y_root + 10}")
        tk.Label(
            self._lock_tooltip,
            text=text,
            bg=BG,
            fg="white",
            relief="solid",
            borderwidth=1,
            font=("Consolas", 8),
            padx=5,
            pady=2,
        ).pack()

    def hide_lock_tooltip(self, event=None):
        if self._lock_tooltip:
            self._lock_tooltip.destroy()
            self._lock_tooltip = None

    # ------------------------------------------------------------- help panel

    def toggle_help(self):
        if self._help_window:
            self.hide_help()
        else:
            self.show_help()

    def show_help(self):
        self.hide_help()
        panel = tk.Toplevel(self.root)
        panel.wm_overrideredirect(True)
        panel.configure(bg=BG, highlightbackground="#3e3e42", highlightthickness=1)

        header = tk.Frame(panel, bg=BAR_BG)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="Quick actions",
            bg=BAR_BG,
            fg=FG,
            font=("Consolas", 9, "bold"),
            padx=8,
            pady=4,
        ).pack(side=tk.LEFT)
        close = tk.Label(
            header,
            text="×",
            bg=BAR_BG,
            fg=MUTED,
            font=("Consolas", 11),
            cursor="hand2",
            padx=8,
        )
        close.pack(side=tk.RIGHT)
        close.bind("<Button-1>", lambda e: self.hide_help())

        body = tk.Frame(panel, bg=BG)
        body.pack(fill=tk.BOTH, padx=10, pady=8)
        for row, (keys, description) in enumerate(HELP_ROWS):
            tk.Label(
                body,
                text=keys,
                bg=BG,
                fg="#9cdcfe",
                font=("Consolas", 8, "bold"),
                anchor="w",
            ).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=1)
            tk.Label(
                body, text=description, bg=BG, fg=FG, font=("Consolas", 8), anchor="w"
            ).grid(row=row, column=1, sticky="w", pady=1)

        panel.update_idletasks()
        x = self.help_btn.winfo_rootx()
        y = self.help_btn.winfo_rooty() + self.help_btn.winfo_height() + 2
        max_x = self.root.winfo_screenwidth() - panel.winfo_reqwidth() - 4
        panel.wm_geometry(f"+{max(4, min(x, max_x))}+{y}")

        self._help_window = panel

    def hide_help(self):
        if self._help_window:
            self._help_window.destroy()
            self._help_window = None

    # -------------------------------------------------------------------- tabs

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

    def _prime_entry(self, text):
        """Load the entry field for a naming step and flag it visually."""
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
        self.entry.delete(0, tk.END)
        self.entry.config(highlightthickness=0)

    def _on_entry_return(self, event=None):
        if self._entry_mode == "new_tab":
            self._commit_new_tab()
        elif self._entry_mode == "rename_tab":
            self._commit_rename_tab()
        else:
            self.add_todo()

    def _on_entry_escape(self, event=None):
        if self._entry_mode != "todo":
            self._leave_entry_mode()
            self.update_counts()
        else:
            self.hide()

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
        self._undo_stack = [
            (i - 1 if i > index else i, snapshot)
            for i, snapshot in self._undo_stack
            if i != index
        ]
        self._switch_tab(min(index, len(self.tabs) - 1))
        self.save_todos()
        self.set_status("Tab deleted")

    def _show_confirm(self, message, on_confirm, anchor_widget):
        """Small themed confirmation popup, sized to fit next to the overlay
        rather than a native OS dialog."""
        self._hide_confirm()
        panel = tk.Toplevel(self.root)
        panel.wm_overrideredirect(True)
        panel.configure(bg=BG, highlightbackground="#3e3e42", highlightthickness=1)

        tk.Label(
            panel,
            text=message,
            bg=BG,
            fg=FG,
            font=("Consolas", 8),
            wraplength=200,
            justify="left",
            padx=10,
            pady=8,
        ).pack(fill=tk.X)

        buttons = tk.Frame(panel, bg=BG)
        buttons.pack(fill=tk.X, padx=10, pady=(0, 8))

        def confirm(event=None):
            self._hide_confirm()
            on_confirm()

        delete_btn = tk.Label(
            buttons,
            text="Delete",
            bg=ERROR_FG,
            fg=BG,
            cursor="hand2",
            font=("Consolas", 8, "bold"),
            padx=8,
            pady=3,
        )
        delete_btn.pack(side=tk.RIGHT)
        delete_btn.bind("<Button-1>", confirm)

        cancel_btn = tk.Label(
            buttons,
            text="Cancel",
            bg="#3e3e42",
            fg=FG,
            cursor="hand2",
            font=("Consolas", 8),
            padx=8,
            pady=3,
        )
        cancel_btn.pack(side=tk.RIGHT, padx=(0, 6))
        cancel_btn.bind("<Button-1>", lambda e: self._hide_confirm())

        panel.update_idletasks()
        x = anchor_widget.winfo_rootx()
        y = anchor_widget.winfo_rooty() - panel.winfo_reqheight() - 4
        max_x = self.root.winfo_screenwidth() - panel.winfo_reqwidth() - 4
        panel.wm_geometry(f"+{max(4, min(x, max_x))}+{max(4, y)}")

        panel.bind("<Escape>", lambda e: self._hide_confirm())
        panel.bind("<Delete>", confirm)
        panel.focus_set()
        self._confirm_window = panel

    def _hide_confirm(self):
        if self._confirm_window:
            self._confirm_window.destroy()
            self._confirm_window = None

    # ------------------------------------------------------------------ todos

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

                keyboard.add_hotkey(
                    "shift+tab", lambda: self._post(self.toggle), suppress=False
                )
                keyboard.wait()
            except Exception as exc:
                message = f"Hotkey unavailable: {exc}"
                self._post(lambda: self.set_status(message, error=True))

        threading.Thread(target=hotkey_thread, daemon=True).start()

    def run(self, instance=None):
        self.instance = instance
        self.setup_hotkey()

        if "--show" in sys.argv:
            self.show()

        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass


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
