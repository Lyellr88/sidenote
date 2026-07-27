#!/usr/bin/env python3
"""
CLI Sidenote - command line interface.

Entry point for the ``sidenote`` command: start, stop, status, init.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from . import lockfile


def _say(message):
    """Print without exploding on legacy console code pages.

    A plain print("✓ ...") raises UnicodeEncodeError under cp1252, which is
    still the default for cmd.exe on many machines.
    """
    try:
        print(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", "replace").decode("ascii"))


def _pythonw():
    """Path to pythonw.exe for the interpreter that's running us.

    Derived from sys.executable rather than looked up on PATH, so the overlay
    runs under the same interpreter (and virtualenv) that has the dependencies
    installed.
    """
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    if candidate.exists():
        return str(candidate)
    # Fall back to the console interpreter; a console window may flash briefly.
    return str(exe)


def _require_windows():
    if sys.platform != "win32":
        _say("Error: CLI Sidenote currently supports Windows only")
        sys.exit(1)


def start():
    """Start the overlay in the background."""
    _require_windows()

    existing = lockfile.running_pid()
    if existing:
        _say(f"✓ Sidenote is already running (PID {existing})")
        _say("  Press Shift+Tab to toggle it")
        return

    subprocess.Popen(
        [_pythonw(), "-m", "cli_sidenote", "--show"],
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
    _say("✓ Sidenote overlay started!")
    _say("  Press Shift+Tab to toggle")


def stop():
    """Stop the overlay.

    Only the PID recorded in the lock file is terminated. The previous version
    ran ``taskkill /F /IM pythonw.exe``, which killed every Python GUI process
    on the machine - dev servers, notebooks, anything else the user had running.
    """
    _require_windows()

    pid = lockfile.running_pid()
    if pid is None:
        lockfile.clear()
        _say("Sidenote is not running.")
        return

    if lockfile.terminate(pid):
        lockfile.clear()
        _say(f"✓ Sidenote overlay stopped (PID {pid})")
    else:
        _say(f"✗ Could not stop PID {pid}. Try again, or end it in Task Manager.")
        sys.exit(1)


def status():
    """Report whether the overlay is running."""
    _require_windows()
    pid = lockfile.running_pid()
    if pid:
        _say(f"Sidenote {_version()} is running (PID {pid})")
    else:
        _say(f"Sidenote {_version()} is not running")


def _version():
    """Installed version string.

    Prefers package metadata, which is authoritative for an installed copy, and
    falls back to the source constant when running from a checkout that was
    never pip-installed.
    """
    try:
        import importlib.metadata as metadata

        return metadata.version("cli-sidenote")
    except Exception:
        try:
            from . import __version__

            return __version__
        except Exception:
            return "unknown"


def _installed_version():
    """Version currently importable, queried in a fresh interpreter.

    Asking a subprocess rather than this process matters after an upgrade: our
    own modules were imported before pip replaced them on disk.
    """
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import importlib.metadata as m; print(m.version('cli-sidenote'))",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _is_editable_install():
    """True when installed with `pip install -e .` from a clone.

    Upgrading such an install from PyPI would silently replace the user's
    working copy with a release build, so we refuse and point at git instead.
    """
    try:
        import importlib.metadata as metadata

        raw = metadata.distribution("cli-sidenote").read_text("direct_url.json")
        if not raw:
            return False
        import json

        return bool(json.loads(raw).get("dir_info", {}).get("editable"))
    except Exception:
        return False


def upgrade():
    """Update to the newest release on PyPI.

    The actual pip run happens in a detached helper process. Windows locks a
    running .exe against overwrite *and* rename, so pip cannot replace
    Scripts/sidenote.exe while `sidenote upgrade` is the running process - it
    would fail with "Access is denied" on any real version change. The helper
    waits for this process to exit, then upgrades.
    """
    _require_windows()

    if _is_editable_install():
        _say("This is an editable install from a local clone, so there is")
        _say("nothing to fetch from PyPI. Update it with:")
        _say("")
        _say("  sidenote stop")
        _say("  git pull")
        _say("  pip install -e .")
        return

    if lockfile.running_pid() is not None:
        _say("Stopping the running overlay first...")
        stop()

    _say(f"Installed version: {_installed_version() or 'unknown'}")
    _say("Opening an upgrade window...")

    try:
        subprocess.Popen(
            [sys.executable, "-m", "cli_sidenote._upgrade", str(os.getpid())],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            close_fds=True,
        )
    except OSError as exc:
        _say(f"✗ Could not start the upgrade helper: {exc}")
        _say("  Run this instead: python -m pip install --upgrade cli-sidenote")
        sys.exit(1)

    _say("")
    _say("The upgrade continues in a separate window - this one can close.")


PROFILE_BLOCK = """
# CLI Sidenote
function start-note { sidenote }
function stop-note  { sidenote stop }
"""


def init():
    """Add PowerShell helper functions to the user's profile.

    These have to be functions, not aliases: PowerShell's Set-Alias cannot carry
    arguments, so aliasing stop-note to `sidenote` made it *start* the overlay.
    """
    _require_windows()

    _say("Setting up PowerShell integration...")

    profile_paths = [
        Path.home() / "Documents" / "PowerShell" / "profile.ps1",
        Path.home() / "Documents" / "WindowsPowerShell" / "profile.ps1",
    ]

    profile_path = next((p for p in profile_paths if p.exists()), None)
    if profile_path is None:
        profile_path = profile_paths[0]
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.touch()

    content = profile_path.read_text(encoding="utf-8", errors="replace")

    if "# CLI Sidenote" in content:
        if "Set-Alias -Name stop-note" in content:
            _say("! Your profile has the old broken aliases in it:")
            _say("    Set-Alias -Name stop-note -Value sidenote")
            _say(
                f"  Remove that block from {profile_path} and run 'sidenote init' again."
            )
            _say(
                "  (stop-note was aliased to plain 'sidenote', so it started the overlay.)"
            )
            sys.exit(1)
        _say("✓ PowerShell functions already configured")
        return

    with open(profile_path, "a", encoding="utf-8") as handle:
        handle.write(PROFILE_BLOCK)

    _say(f"✓ Functions added to: {profile_path}")
    _say("\nRestart PowerShell or run: . $PROFILE")
    _say("\nThen you can use:")
    _say("  start-note  # same as 'sidenote'")
    _say("  stop-note   # same as 'sidenote stop'")


TAGLINE = "CLI Sidenote - a zero-friction todo overlay for your terminal"
DOCS_URL = "https://github.com/lyellr88/cli-sidenote"

# Single source of truth: the help listing, argparse's `choices`, and the
# dispatch table are all derived from this, so they cannot drift apart.
COMMANDS = [
    ("start", "Start the overlay (default when no command is given)"),
    ("stop", "Stop the overlay"),
    ("status", "Show whether the overlay is running, with its PID"),
    ("upgrade", "Update to the newest release from PyPI"),
    ("init", "Add start-note / stop-note shortcuts to PowerShell"),
]

OPTIONS = [
    ("-h, --help", "Show this help and exit"),
    ("-V, --version", "Show the version and exit"),
]

HOTKEYS = [
    ("Shift+Tab", "Toggle the overlay from any application"),
    ("Enter", "Add a todo"),
    ("Double-click", "Check off / uncheck a todo"),
    ("Delete", "Remove the selected todo"),
    ("Ctrl+Delete", "Clear all checked-off todos"),
]

EXAMPLES = [
    ("sidenote", "Start it, then press Shift+Tab anywhere"),
    ("sidenote status", "Check whether it's running"),
    ("sidenote upgrade", "Update to the latest version"),
]

_GUTTER = 21


def _rows(pairs):
    """Two-column rows, aligned on a fixed gutter."""
    return [f"  {name.ljust(_GUTTER)}{description}" for name, description in pairs]


def _format_help():
    """Hand-rolled help.

    argparse renders a positional with `choices` as a cramped `{a,b,c}` blob
    with one shared description, which tells the reader nothing about what each
    command does.
    """
    lines = [
        TAGLINE,
        "",
        "Usage: sidenote [command] [options]",
        "",
        "Commands:",
        *_rows(COMMANDS),
        "",
        "Options:",
        *_rows(OPTIONS),
        "",
        "Hotkeys (while running):",
        *_rows(HOTKEYS),
        "",
        "Examples:",
        *_rows(EXAMPLES),
        "",
        f"Docs: {DOCS_URL}",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        prog="sidenote",  # otherwise argparse shows the full python.exe path
        usage="sidenote [command] [options]",
        description=TAGLINE,
        add_help=False,
    )
    parser.add_argument(
        "command", nargs="?", choices=[name for name, _ in COMMANDS], help=argparse.SUPPRESS
    )
    parser.add_argument(
        "-h", "--help", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"cli-sidenote {_version()}",
        help=argparse.SUPPRESS,
    )
    parser.format_help = _format_help

    args = parser.parse_args()

    if args.help:
        _say(_format_help().rstrip("\n"))
        return

    dispatch = {
        "start": start,
        "stop": stop,
        "status": status,
        "upgrade": upgrade,
        "init": init,
    }
    dispatch[args.command or "start"]()


if __name__ == "__main__":
    main()
