#!/usr/bin/env python3
"""
Windows-specific helpers: terminal detection, DPI handling, and window event hooks.

Two things here matter for correctness:

* Terminals are identified by the *executable* behind the window, not by a
  substring of the window title. Title matching treats a browser tab named
  "PowerShell docs" as a terminal.
* Window changes arrive via SetWinEventHook rather than a polling loop, so the
  overlay reacts immediately and costs nothing while idle.
"""

import ctypes
import os
import threading
from ctypes import wintypes

import win32con
import win32gui
import win32process

TERMINAL_EXES = {
    "windowsterminal.exe",
    "wt.exe",
    "powershell.exe",
    "pwsh.exe",
    "cmd.exe",
    "conhost.exe",
    "openconsole.exe",
    "alacritty.exe",
    "wezterm-gui.exe",
}

EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MOVESIZESTART = 0x000A
EVENT_SYSTEM_MOVESIZEEND = 0x000B
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND = 0x0017
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_LOCATIONCHANGE = 0x800B

WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
OBJID_WINDOW = 0
DWMWA_CLOAKED = 14
DWMWA_EXTENDED_FRAME_BOUNDS = 9

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

_WinEventProc = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.HWND,
    wintypes.LONG,
    wintypes.LONG,
    wintypes.DWORD,
    wintypes.DWORD,
)

_user32.SetWinEventHook.argtypes = [
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HMODULE,
    _WinEventProc,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
]
_user32.SetWinEventHook.restype = wintypes.HANDLE
_user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
_user32.UnhookWinEvent.restype = wintypes.BOOL


def enable_dpi_awareness():
    """Opt into per-monitor DPI so win32 rectangles are real pixels.

    Without this Windows virtualises coordinates on scaled displays and the
    overlay lands in the wrong place next to the terminal.
    """
    try:  # Windows 10 1703+
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:  # Windows 8.1+
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def dpi_for_window(hwnd):
    """Effective DPI for a window's monitor; 96 when unavailable."""
    try:
        dpi = ctypes.windll.user32.GetDpiForWindow(wintypes.HWND(hwnd))
        if dpi:
            return int(dpi)
    except (AttributeError, OSError):
        pass
    return 96


def is_cloaked(hwnd):
    """True for DWM-cloaked windows (hidden UWP/virtual-desktop shells).

    These are visible to EnumWindows but not to the user, and Windows Terminal
    keeps a few around - attaching to one puts the overlay in empty space.
    """
    value = ctypes.c_int(0)
    try:
        result = _dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(DWMWA_CLOAKED),
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    except OSError:
        return False
    return result == 0 and value.value != 0


def process_name(hwnd):
    """Lowercased executable name owning a window, or '' if unknown."""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except Exception:
        return ""
    if not pid:
        return ""

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(
            wintypes.HANDLE(handle), 0, buf, ctypes.byref(size)
        ):
            return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(wintypes.HANDLE(handle))
    return ""


def is_terminal(hwnd, own_pid=None):
    """Whether a window is a usable terminal window."""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
        return False
    if win32gui.GetParent(hwnd):  # child windows are never the terminal frame
        return False
    if not win32gui.GetWindowText(hwnd):
        return False
    if is_cloaked(hwnd):
        return False
    if own_pid is not None:
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == own_pid:
                return False
        except Exception:
            pass
    return process_name(hwnd) in TERMINAL_EXES


def find_terminal(own_pid=None):
    """Best terminal window: the focused one if it qualifies, else topmost."""
    foreground = win32gui.GetForegroundWindow()
    if is_terminal(foreground, own_pid):
        return foreground

    found = []

    def callback(hwnd, acc):
        if is_terminal(hwnd, own_pid):
            acc.append(hwnd)
        return True

    try:
        win32gui.EnumWindows(callback, found)
    except Exception:
        return None
    return found[0] if found else None


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def visible_rect(hwnd):
    """The rectangle the user actually sees, as (left, top, right, bottom).

    GetWindowRect includes Windows' invisible resize border (roughly 8px per
    side), so aligning two windows by it leaves a visible gap and a height
    mismatch. DWM's extended frame bounds are the drawn edges.
    """
    rect = _RECT()
    try:
        if (
            _dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(hwnd),
                wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            == 0
        ):
            return rect.left, rect.top, rect.right, rect.bottom
    except OSError:
        pass
    return win32gui.GetWindowRect(hwnd)


def window_metrics(hwnd):
    """(offset_x, offset_y, chrome_w, chrome_h) for positioning a window.

    offset_* is how far the visible edge sits inside the window rect, since tk's
    geometry positions the window rect. chrome_* is the visible border plus
    title bar, measured rather than hardcoded so it holds across DPI settings
    and Windows versions.
    """
    try:
        wl, wt, _, _ = win32gui.GetWindowRect(hwnd)
        vl, vt, vr, vb = visible_rect(hwnd)
        _, _, client_w, client_h = win32gui.GetClientRect(hwnd)
        return (
            vl - wl,
            vt - wt,
            max(0, (vr - vl) - client_w),
            max(0, (vb - vt) - client_h),
        )
    except Exception:
        return 0, 0, 0, 0


def bring_to_front(hwnd):
    """Raise a window without making it permanently topmost or stealing focus."""
    flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE
    try:
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags)
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)
    except Exception:
        pass


class WindowEventListener:
    """Runs SetWinEventHook on a dedicated thread with its own message pump.

    ``callback(event, hwnd)`` is invoked from that thread, so consumers must
    marshal anything GUI-related back to the main thread themselves.
    """

    EVENTS = (
        (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MOVESIZEEND),
        (EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND),
        (EVENT_OBJECT_DESTROY, EVENT_OBJECT_DESTROY),
        (EVENT_OBJECT_LOCATIONCHANGE, EVENT_OBJECT_LOCATIONCHANGE),
    )

    def __init__(self, callback):
        self.callback = callback
        self._thread = None
        self._proc = _WinEventProc(self._dispatch)
        self._hooks = []

    def _dispatch(self, hook, event, hwnd, id_object, id_child, thread_id, time_ms):
        if id_object != OBJID_WINDOW or id_child != 0:
            return
        if not hwnd:
            return
        try:
            self.callback(event, hwnd)
        except Exception:
            pass

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        for low, high in self.EVENTS:
            hook = _user32.SetWinEventHook(
                low,
                high,
                None,
                self._proc,
                0,
                0,
                WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
            )
            if hook:
                self._hooks.append(hook)

        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

        for hook in self._hooks:
            _user32.UnhookWinEvent(hook)
        self._hooks = []
