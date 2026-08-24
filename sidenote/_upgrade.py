#!/usr/bin/env python3
"""
Detached helper that upgrades the package after its launcher has exited.

Windows locks a running executable against both overwrite *and* rename, so pip
cannot replace ``Scripts/sidenote.exe`` while that very executable is the
running process - `sidenote upgrade` would fail with "Access is denied" on any
real version change. This helper is spawned in its own console, waits for the
parent `sidenote` process to exit, and only then runs pip.

Only the standard library is imported here, and everything is imported up front:
pip replaces this package's files mid-run, so nothing may be imported lazily
afterwards.
"""

import contextlib
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

PACKAGE = "sidenote"
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0


def _pause():
    """Keep the console window open, unless there's no stdin to read."""
    with contextlib.suppress(EOFError, OSError):
        input("\nPress Enter to close...")


def _wait_for_exit(pid, timeout_ms=30000):
    """Block until pid exits. True if it's gone, False on timeout."""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

    handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return True  # already exited, or we can't see it - either way, proceed
    try:
        return kernel32.WaitForSingleObject(handle, timeout_ms) == WAIT_OBJECT_0
    finally:
        kernel32.CloseHandle(handle)


def main():
    parent_pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    print("Sidenote - upgrade")
    print("=" * 40)
    print()

    if parent_pid:
        print("Waiting for sidenote to close...")
        if not _wait_for_exit(parent_pid):
            print()
            print("Timed out waiting for the previous sidenote process to exit.")
            print("Close any terminal running sidenote, then run:")
            print(f"  python -m pip install --upgrade --no-cache-dir {PACKAGE}")
            _pause()
            return 1
        time.sleep(0.5)

    print()
    # --no-cache-dir: pip's local metadata cache can outlive a release by
    # hours, and `install --upgrade` trusts it rather than re-checking PyPI -
    # so right after a new version ships, this silently no-ops with
    # "Requirement already satisfied" instead of upgrading anything.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--no-cache-dir",
            PACKAGE,
        ],
        check=False,
    )

    print()
    if result.returncode == 0:
        print("Upgrade complete. Run 'sidenote' to start it again.")
    else:
        print("Upgrade failed. You can retry manually with:")
        print(f"  python -m pip install --upgrade --no-cache-dir {PACKAGE}")

    _pause()
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
