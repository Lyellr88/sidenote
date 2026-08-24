#!/usr/bin/env python3
"""
Single-instance lock backed by a PID file.

The lock file holds the PID of the running overlay. Every consumer checks that
the PID is (a) alive and (b) actually a Python process before trusting it - a
bare "does the file exist" check leaves the app permanently unstartable after a
crash, and a bare "is the PID alive" check can match an unrelated process that
inherited a recycled PID.
"""

import contextlib
import ctypes
import os
from ctypes import wintypes
from pathlib import Path

LOCK_FILE = Path(os.path.expanduser("~")) / ".terminal_overlay.lock"

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
STILL_ACTIVE = 259
WAIT_OBJECT_0 = 0

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.GetExitCodeProcess.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.DWORD),
]
_kernel32.GetExitCodeProcess.restype = wintypes.BOOL
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_kernel32.TerminateProcess.restype = wintypes.BOOL
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD


def _open(pid, access):
    handle = _kernel32.OpenProcess(access, False, pid)
    return handle or None


def _image_name(handle):
    """Full path of a process's executable, or '' if it can't be read."""
    size = wintypes.DWORD(32768)
    buf = ctypes.create_unicode_buffer(size.value)
    if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
        return buf.value
    return ""


def is_overlay_pid(pid):
    """True only if pid is alive AND is a Python interpreter.

    The image-name check is what makes PID reuse safe: without it, a recycled
    PID belonging to some unrelated program would look like a live overlay.
    """
    if not pid or pid <= 0:
        return False

    handle = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if handle is None:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        if exit_code.value != STILL_ACTIVE:
            return False
        name = os.path.basename(_image_name(handle)).lower()
        return name.startswith("python")
    finally:
        _kernel32.CloseHandle(handle)


def read_pid(lock_file=LOCK_FILE):
    """PID recorded in the lock file, or None if absent/corrupt."""
    try:
        return int(Path(lock_file).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def running_pid(lock_file=LOCK_FILE):
    """PID of the live overlay, or None. Clears the lock if it went stale."""
    pid = read_pid(lock_file)
    if pid is None:
        return None
    if is_overlay_pid(pid):
        return pid
    clear(lock_file)
    return None


def clear(lock_file=LOCK_FILE):
    with contextlib.suppress(OSError):
        Path(lock_file).unlink()


def terminate(pid, timeout_ms=3000):
    """Terminate one specific PID. Returns True if it is gone afterwards."""
    handle = _open(pid, PROCESS_TERMINATE | SYNCHRONIZE)
    if handle is None:
        return not is_overlay_pid(pid)
    try:
        _kernel32.TerminateProcess(handle, 0)
        return _kernel32.WaitForSingleObject(handle, timeout_ms) == WAIT_OBJECT_0
    finally:
        _kernel32.CloseHandle(handle)


class SingleInstance:
    """Context manager yielding True if this process owns the lock."""

    def __init__(self, lock_file=LOCK_FILE):
        self.lock_file = Path(lock_file)
        self.locked = False

    def __enter__(self):
        if running_pid(self.lock_file) is not None:
            return False
        self.lock_file.write_text(str(os.getpid()), encoding="utf-8")
        self.locked = True
        return True

    def __exit__(self, *args):
        self.release()
        return False

    def release(self):
        if self.locked and read_pid(self.lock_file) == os.getpid():
            clear(self.lock_file)
        self.locked = False
