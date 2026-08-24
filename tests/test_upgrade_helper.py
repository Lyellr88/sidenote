"""The detached upgrade helper: waiting for the launcher to release its lock."""

import subprocess
import sys
import time

import pytest

from sidenote import _upgrade


@pytest.fixture
def sleeper():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    yield proc
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=5)


def test_wait_returns_immediately_for_dead_pid(sleeper):
    sleeper.kill()
    sleeper.wait(timeout=5)
    started = time.monotonic()
    assert _upgrade._wait_for_exit(sleeper.pid, timeout_ms=5000) is True
    assert time.monotonic() - started < 2, "should not have blocked"


def test_wait_returns_true_for_unknown_pid():
    """An unopenable PID means there's nothing to wait for - proceed."""
    assert _upgrade._wait_for_exit(999999, timeout_ms=1000) is True


def test_wait_blocks_until_process_exits(sleeper):
    """The whole point: don't run pip until the launcher has released its lock."""
    assert _upgrade._wait_for_exit(sleeper.pid, timeout_ms=300) is False  # times out

    sleeper.kill()
    sleeper.wait(timeout=5)

    assert _upgrade._wait_for_exit(sleeper.pid, timeout_ms=5000) is True


def test_wait_detects_exit_that_happens_while_waiting(sleeper):
    import threading

    threading.Timer(0.5, sleeper.kill).start()
    assert _upgrade._wait_for_exit(sleeper.pid, timeout_ms=10000) is True


def test_pause_survives_missing_stdin(monkeypatch, capsys):
    """Under pythonw or redirected input, input() raises - must not crash."""

    def no_stdin(prompt=""):
        raise EOFError("no stdin")

    monkeypatch.setattr("builtins.input", no_stdin)
    _upgrade._pause()  # must not raise


def test_helper_module_is_runnable():
    """It must be importable as `python -m sidenote._upgrade`."""
    result = subprocess.run(
        [sys.executable, "-c", "import sidenote._upgrade as u; print(u.PACKAGE)"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "sidenote"


def test_pip_upgrade_bypasses_pips_cache(monkeypatch):
    """Without --no-cache-dir, pip can trust stale local metadata and report
    "Requirement already satisfied" for a version that's no longer latest -
    `sidenote upgrade` would then claim success having upgraded nothing."""
    captured = {}

    class FakeResult:
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeResult()

    monkeypatch.setattr(_upgrade.subprocess, "run", fake_run)
    monkeypatch.setattr(_upgrade, "_pause", lambda: None)
    monkeypatch.setattr(sys, "argv", ["_upgrade.py"])  # no parent pid - skip the wait

    assert _upgrade.main() == 0
    assert "--no-cache-dir" in captured["cmd"]


def test_helper_only_imports_stdlib_at_module_level():
    """pip rewrites this package mid-run, so nothing may be imported lazily."""
    source = __import__("pathlib").Path(_upgrade.__file__).read_text(encoding="utf-8")
    # No imports of our own package - those files are being replaced underneath.
    assert "from . import" not in source
    assert "import sidenote" not in source
