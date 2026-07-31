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
# Just enough lift off LIST_BG to locate the selection without it grabbing the eye.
SELECT_BG = "#2f3033"
FG = "#cccccc"
MUTED = "#858585"
DONE_FG = "#6a6a6a"
ERROR_FG = "#f48771"
LOCKED_BG = "#8b0000"

BASE_WIDTH = 280
PUMP_MS = 40
FALLBACK_POLL_MS = 2000
REPOSITION_DEBOUNCE_MS = 60

# Steps a copied row fades through on its way back to normal.
COPY_FLASH = ["#4ec9b0", "#3f9c88", "#317a6c"]
COPY_FLASH_MS = 70

HELP_ROWS = [
    ("Shift+Tab", "Toggle overlay (works anywhere)"),
    ("Enter", "Add todo"),
    ("Double-click", "Check off / uncheck a todo"),
    ("Right-click", "Copy a todo's text"),
    ("Space", "Check off / uncheck selection"),
    ("Delete", "Remove selected todo"),
    ("Ctrl+Delete", "Clear all checked-off todos"),
    ("Escape", "Hide overlay"),
    ("Lock button", "Stick to one specific terminal"),
    ("Drag title bar", "Detach and place it yourself"),
]


class TerminalOverlay:
    def __init__(self):
        self.root = tk.Tk()
        self.visible = False
        self.todos = []
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
        self._scale = 1.0
        self._user_width = None
        self._applied_w = None

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

        self.help_btn = tk.Label(
            drag_bar,
            text="?",
            bg=BAR_BG,
            fg=FG,
            cursor="hand2",
            font=("Consolas", 10, "bold"),
            padx=6,
        )
        self.help_btn.pack(side=tk.LEFT)
        self.help_btn.bind("<Button-1>", lambda e: self.toggle_help())

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

        # place(), not pack(): the two buttons are different widths, so packing
        # the title into what's left between them centres it off-centre.
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
        )
        self.entry.pack(fill=tk.X)
        self.entry.bind("<Return>", self.add_todo)
        self.entry.bind("<Escape>", lambda e: self.hide())

        list_container = tk.Frame(self.root, bg=BG)
        list_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=0)

        # No scrollbar: the list still scrolls by wheel, and by arrow keys once
        # a row is selected.
        self.listbox = tk.Listbox(
            list_container,
            bg=LIST_BG,
            fg=FG,
            selectbackground=SELECT_BG,
            # Empty means "keep the row's own colour", so selecting a done todo
            # doesn't wash out its grey, and the copy flash still shows.
            selectforeground="",
            relief="flat",
            font=("Consolas", 9),
            bd=0,
            # Default is a 1px SystemButtonFace ring, which reads as a white
            # border whenever the list doesn't have focus.
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

        footer = tk.Frame(self.root, bg=BAR_BG, height=30)
        footer.pack(fill=tk.X)
        footer.pack_propagate(False)

        self.status = tk.Label(
            footer, text="", fg=MUTED, bg=BAR_BG, font=("Consolas", 8), anchor="center"
        )
        self.status.pack(fill=tk.X, pady=6)

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

        # Scale to the terminal's monitor instead of assuming 96 DPI.
        self._apply_scaling(winutil.dpi_for_window(terminal))

        # tk sizes the client area and positions the *window* rect, so subtract
        # this window's chrome and shift by its invisible border to make the
        # visible edges sit flush against the terminal. A width the user dragged
        # is already a client width, so it needs no such adjustment.
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
            self.set_status("Unlocked")
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
        self.set_status("Locked to this terminal")

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
        # Keep the panel on screen when the overlay sits near a screen edge.
        max_x = self.root.winfo_screenwidth() - panel.winfo_reqwidth() - 4
        panel.wm_geometry(f"+{max(4, min(x, max_x))}+{y}")

        self._help_window = panel

    def hide_help(self):
        if self._help_window:
            self._help_window.destroy()
            self._help_window = None

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
        self.todos = remaining
        self.refresh_list()
        self.save_todos()
        self.set_status(f"Cleared {removed} done")
        return "break"

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
        error = storage.save(self.todos)
        if error:
            # Previously swallowed: a full or read-only disk meant todos stopped
            # persisting with no sign of it until a restart lost them.
            self.set_status(error, error=True)
        else:
            self.update_counts()

    def load_todos(self):
        self.todos, error = storage.load()
        self.refresh_list()
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
