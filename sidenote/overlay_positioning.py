"""Terminal window tracking: detecting it, following its movement, and
keeping the overlay positioned and sized to match - plus the lock that pins
the overlay to one specific terminal.
"""

import tkinter as tk

from . import winutil
from .overlay_theme import (
    BAR_BG,
    BASE_WIDTH,
    FALLBACK_POLL_MS,
    LOCKED_BG,
    REPOSITION_DEBOUNCE_MS,
)


class PositioningMixin:
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

    # ------------------------------------------------------------------ lock

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
