"""Lock file: liveness, PID-reuse safety, stale-lock recovery."""

import os
import subprocess
import sys

import pytest

from cli_sidenote import lockfile


@pytest.fixture
def lock_path(tmp_path):
    return tmp_path / "overlay.lock"


@pytest.fixture
def sleeper():
    """A short-lived real Python process to point PIDs at."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    yield proc
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=5)


# ------------------------------------------------------------- pid liveness


def test_current_process_is_recognised():
    assert lockfile.is_overlay_pid(os.getpid()) is True


def test_live_python_child_is_recognised(sleeper):
    assert lockfile.is_overlay_pid(sleeper.pid) is True


def test_dead_pid_is_rejected(sleeper):
    sleeper.kill()
    sleeper.wait(timeout=5)
    assert lockfile.is_overlay_pid(sleeper.pid) is False


def test_non_python_process_is_rejected():
    """PID-reuse guard: a recycled PID owned by something else is not us.

    PID 4 is the Windows System process, which is always running and is
    definitely not a Python interpreter.
    """
    assert lockfile.is_overlay_pid(4) is False


@pytest.mark.parametrize("pid", [0, -1, None, 999999])
def test_invalid_pids_are_rejected(pid):
    assert lockfile.is_overlay_pid(pid) is False


# ----------------------------------------------------------- lock file I/O


def test_read_pid_missing_file(lock_path):
    assert lockfile.read_pid(lock_path) is None


def test_read_pid_corrupt_file(lock_path):
    lock_path.write_text("not a number")
    assert lockfile.read_pid(lock_path) is None


def test_read_pid_round_trip(lock_path):
    lock_path.write_text("12345")
    assert lockfile.read_pid(lock_path) == 12345


def test_running_pid_returns_live_pid(lock_path, sleeper):
    lock_path.write_text(str(sleeper.pid))
    assert lockfile.running_pid(lock_path) == sleeper.pid


def test_stale_lock_is_cleared_not_honoured(lock_path, sleeper):
    """The old bug: a leftover lock file made the app permanently unstartable."""
    sleeper.kill()
    sleeper.wait(timeout=5)
    lock_path.write_text(str(sleeper.pid))

    assert lockfile.running_pid(lock_path) is None
    assert not lock_path.exists()


def test_clear_is_safe_when_absent(lock_path):
    lockfile.clear(lock_path)  # must not raise


# ------------------------------------------------------------- termination


def test_terminate_kills_only_the_target(sleeper):
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert lockfile.terminate(sleeper.pid) is True
        sleeper.wait(timeout=5)
        # The bystander is what `taskkill /IM python.exe` used to destroy.
        assert lockfile.is_overlay_pid(other.pid) is True
    finally:
        other.kill()
        other.wait(timeout=5)


def test_terminate_on_dead_pid_reports_gone(sleeper):
    sleeper.kill()
    sleeper.wait(timeout=5)
    assert lockfile.terminate(sleeper.pid) is True


# --------------------------------------------------------- SingleInstance


def test_single_instance_acquires_and_releases(lock_path):
    with lockfile.SingleInstance(lock_path) as acquired:
        assert acquired is True
        assert lockfile.read_pid(lock_path) == os.getpid()
    assert not lock_path.exists()


def test_second_instance_is_refused(lock_path):
    with lockfile.SingleInstance(lock_path) as first:
        assert first is True
        with lockfile.SingleInstance(lock_path) as second:
            assert second is False


def test_single_instance_reclaims_stale_lock(lock_path, sleeper):
    sleeper.kill()
    sleeper.wait(timeout=5)
    lock_path.write_text(str(sleeper.pid))

    with lockfile.SingleInstance(lock_path) as acquired:
        assert acquired is True
        assert lockfile.read_pid(lock_path) == os.getpid()


def test_release_does_not_delete_another_instances_lock(lock_path):
    """A refused instance must not clear the winner's lock on exit."""
    winner = lockfile.SingleInstance(lock_path)
    assert winner.__enter__() is True

    loser = lockfile.SingleInstance(lock_path)
    assert loser.__enter__() is False
    loser.__exit__()

    assert lock_path.exists()
    assert lockfile.read_pid(lock_path) == os.getpid()
    winner.__exit__()
