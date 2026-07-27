"""Window helpers: process-based detection and geometry maths.

These run against the live desktop, so they assert on invariants rather than on
specific windows, which vary by machine.
"""

import os

import pytest
import win32gui

from cli_sidenote import winutil


def test_terminal_exe_list_is_lowercase():
    # process_name() lowercases before comparing; an uppercase entry here would
    # silently never match.
    assert all(name == name.lower() for name in winutil.TERMINAL_EXES)


def test_process_name_of_our_own_window(tmp_path):
    """process_name resolves a real hwnd to the owning executable."""
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    try:
        root.update_idletasks()
        hwnd = int(root.wm_frame(), 16)
        assert winutil.process_name(hwnd).startswith("python")
    finally:
        root.destroy()


def test_process_name_of_invalid_hwnd_is_empty():
    assert winutil.process_name(0) == ""
    assert winutil.process_name(123456789) == ""


def test_is_terminal_rejects_invalid_hwnd():
    assert winutil.is_terminal(0) is False
    assert winutil.is_terminal(None) is False


def test_is_terminal_rejects_the_desktop_window():
    """The old title-substring match had no way to exclude non-terminals."""
    desktop = win32gui.GetDesktopWindow()
    assert winutil.is_terminal(desktop) is False


def test_found_terminals_are_really_terminal_processes():
    """Every window the detector accepts is backed by a terminal executable."""
    found = []

    def callback(hwnd, acc):
        if winutil.is_terminal(hwnd):
            acc.append(hwnd)
        return True

    win32gui.EnumWindows(callback, found)

    for hwnd in found:
        assert winutil.process_name(hwnd) in winutil.TERMINAL_EXES
        assert win32gui.IsWindowVisible(hwnd)
        assert not winutil.is_cloaked(hwnd)


def test_is_terminal_excludes_our_own_process():
    """The overlay must never try to attach to itself."""
    found = []

    def callback(hwnd, acc):
        if winutil.is_terminal(hwnd, own_pid=os.getpid()):
            acc.append(hwnd)
        return True

    win32gui.EnumWindows(callback, found)

    import win32process

    for hwnd in found:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        assert pid != os.getpid()


def test_dpi_for_window_has_sane_fallback():
    assert winutil.dpi_for_window(win32gui.GetDesktopWindow()) >= 96
    assert winutil.dpi_for_window(0) == 96  # invalid hwnd -> documented default


def test_visible_rect_is_within_window_rect():
    """DWM's visible bounds sit inside the window rect's invisible border."""
    desktop = win32gui.GetDesktopWindow()
    wl, wt, wr, wb = win32gui.GetWindowRect(desktop)
    vl, vt, vr, vb = winutil.visible_rect(desktop)
    assert vl >= wl and vt >= wt and vr <= wr and vb <= wb


def test_window_metrics_are_non_negative_for_invalid_hwnd():
    assert winutil.window_metrics(0) == (0, 0, 0, 0)


def test_event_listener_keeps_callback_alive():
    """The ctypes trampoline must be referenced, or Windows calls freed memory."""
    listener = winutil.WindowEventListener(lambda event, hwnd: None)
    assert listener._proc is not None


def test_event_listener_filters_non_window_events():
    """LOCATIONCHANGE fires for carets and cursors; only windows should pass."""
    seen = []
    listener = winutil.WindowEventListener(lambda event, hwnd: seen.append(hwnd))

    # idObject != OBJID_WINDOW - must be ignored
    listener._dispatch(None, winutil.EVENT_OBJECT_LOCATIONCHANGE, 999, -8, 0, 0, 0)
    assert seen == []

    # idChild != 0 - must be ignored
    listener._dispatch(None, winutil.EVENT_OBJECT_LOCATIONCHANGE, 999, 0, 3, 0, 0)
    assert seen == []

    # a genuine window event - must pass through
    listener._dispatch(None, winutil.EVENT_OBJECT_LOCATIONCHANGE, 999, 0, 0, 0, 0)
    assert seen == [999]


def test_event_listener_swallows_callback_errors():
    """A raising callback must not kill the hook thread."""

    def boom(event, hwnd):
        raise RuntimeError("callback exploded")

    listener = winutil.WindowEventListener(boom)
    listener._dispatch(None, winutil.EVENT_SYSTEM_FOREGROUND, 999, 0, 0, 0, 0)
