"""CLI behaviour: safe output, targeted stop, and correct profile integration."""

import os
import sys
from pathlib import Path

import pytest

from sidenote import cli, lockfile


@pytest.fixture
def isolated_lock(tmp_path, monkeypatch):
    """Point the CLI's lock helpers at a temp file, never the real one."""
    lock = tmp_path / "overlay.lock"
    real_running_pid = lockfile.running_pid
    real_clear = lockfile.clear
    monkeypatch.setattr(
        cli.lockfile, "running_pid", lambda *a, **k: real_running_pid(lock)
    )
    monkeypatch.setattr(cli.lockfile, "clear", lambda *a, **k: real_clear(lock))
    return lock


# ------------------------------------------------------------------ output


def test_say_handles_unencodable_characters(capsys, monkeypatch):
    """cmd.exe defaults to cp1252, where a bare print('✓') raises."""
    real_print = print
    calls = []

    def fake_print(message):
        calls.append(message)
        if len(calls) == 1:
            raise UnicodeEncodeError("charmap", "✓", 0, 1, "undefined")
        real_print(message)

    monkeypatch.setattr("builtins.print", fake_print)
    cli._say("✓ done")

    out = capsys.readouterr().out
    assert "done" in out
    assert "✓" not in out


def test_say_passes_through_normally(capsys):
    cli._say("plain text")
    assert "plain text" in capsys.readouterr().out


# ----------------------------------------------------------------- pythonw


def test_pythonw_is_derived_from_current_interpreter():
    """Must not depend on PATH, or it can pick a different interpreter."""
    resolved = Path(cli._pythonw())
    assert resolved.parent == Path(sys.executable).parent
    assert resolved.stem in ("pythonw", Path(sys.executable).stem)


# -------------------------------------------------------------------- stop


def test_stop_when_not_running_is_graceful(isolated_lock, capsys):
    cli.stop()
    assert "not running" in capsys.readouterr().out.lower()


def test_stop_targets_only_the_recorded_pid(isolated_lock, capsys, monkeypatch):
    """Regression guard for `taskkill /F /IM python.exe`.

    Whatever stop() does, it must be scoped to the PID in the lock file.
    """
    killed = []
    monkeypatch.setattr(cli.lockfile, "running_pid", lambda *a, **k: 4242)
    monkeypatch.setattr(
        cli.lockfile, "terminate", lambda pid, **k: (killed.append(pid), True)[1]
    )

    cli.stop()

    assert killed == [4242]
    assert "4242" in capsys.readouterr().out


def test_stop_reports_failure_with_nonzero_exit(isolated_lock, monkeypatch):
    monkeypatch.setattr(cli.lockfile, "running_pid", lambda *a, **k: 4242)
    monkeypatch.setattr(cli.lockfile, "terminate", lambda pid, **k: False)

    with pytest.raises(SystemExit) as excinfo:
        cli.stop()
    assert excinfo.value.code == 1


# ------------------------------------------------------------------- start


def test_start_refuses_to_launch_a_second_copy(isolated_lock, capsys, monkeypatch):
    launched = []
    monkeypatch.setattr(cli.lockfile, "running_pid", lambda *a, **k: 4242)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: launched.append(a))

    cli.start()

    assert launched == []
    assert "already running" in capsys.readouterr().out.lower()


def test_start_launches_the_package_module(isolated_lock, monkeypatch):
    launched = []
    monkeypatch.setattr(cli.lockfile, "running_pid", lambda *a, **k: None)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd, **k: launched.append(cmd))

    cli.start()

    assert launched, "expected the overlay to be launched"
    cmd = launched[0]
    assert cmd[1:] == ["-m", "sidenote", "--show"]


# -------------------------------------------------------------------- help


def test_help_lists_every_command_with_its_own_description(capsys, monkeypatch):
    """argparse's default renders `{start,stop,...}` with one shared blurb."""
    monkeypatch.setattr(sys, "argv", ["sidenote", "--help"])
    cli.main()
    out = capsys.readouterr().out

    for name, description in cli.COMMANDS:
        assert f"  {name}" in out, f"{name} missing from help"
        assert description in out, f"description for {name} missing"


def test_help_does_not_leak_the_interpreter_path(capsys, monkeypatch):
    """The default prog is the full python.exe path, which looks broken."""
    monkeypatch.setattr(sys, "argv", ["sidenote", "--help"])
    cli.main()
    out = capsys.readouterr().out

    assert "Usage: sidenote [command] [options]" in out
    assert "python.exe" not in out
    assert ".exe" not in out


def test_short_help_flag_works(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["sidenote", "-h"])
    cli.main()
    assert "Usage: sidenote" in capsys.readouterr().out


def test_help_does_not_run_a_command(capsys, monkeypatch):
    called = []
    for name, _ in cli.COMMANDS:
        monkeypatch.setattr(cli, name, lambda n=name: called.append(n))
    monkeypatch.setattr(sys, "argv", ["sidenote", "--help"])

    cli.main()

    assert called == [], "help must not start the overlay"


def test_help_sections_are_present(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["sidenote", "--help"])
    cli.main()
    out = capsys.readouterr().out

    for heading in ("Commands:", "Options:", "Hotkeys", "Examples:", "Docs:"):
        assert heading in out


ALL_HELP_ROWS = cli.COMMANDS + cli.OPTIONS + cli.HOTKEYS + cli.EXAMPLES


@pytest.mark.parametrize("label,description", ALL_HELP_ROWS)
def test_help_rows_are_aligned(label, description, capsys, monkeypatch):
    """Every description starts at the same column, or the listing looks ragged."""
    assert len(label) < cli._GUTTER, f"{label!r} is too wide for the gutter"

    monkeypatch.setattr(sys, "argv", ["sidenote", "--help"])
    cli.main()
    lines = capsys.readouterr().out.splitlines()

    expected = f"  {label.ljust(cli._GUTTER)}{description}"
    assert expected in lines
    assert expected.index(description) == 2 + cli._GUTTER


def test_help_fits_a_standard_terminal(capsys, monkeypatch):
    """Wrapped help lines look broken; keep rows inside 80 columns."""
    monkeypatch.setattr(sys, "argv", ["sidenote", "--help"])
    cli.main()

    too_long = [ln for ln in capsys.readouterr().out.splitlines() if len(ln) > 80]
    assert too_long == [], f"lines exceed 80 columns: {too_long}"


def test_command_list_matches_dispatch(monkeypatch):
    """Adding a command to COMMANDS without wiring it up must fail loudly."""
    dispatched = []
    for name, _ in cli.COMMANDS:
        monkeypatch.setattr(cli, name, lambda n=name: dispatched.append(n))

    for name, _ in cli.COMMANDS:
        monkeypatch.setattr(sys, "argv", ["sidenote", name])
        cli.main()

    assert dispatched == [name for name, _ in cli.COMMANDS]


def test_unknown_command_is_rejected(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["sidenote", "definitely-not-a-command"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


# ----------------------------------------------------------------- version


def test_version_matches_package_metadata():
    import importlib.metadata as metadata

    assert cli._version() == metadata.version("sidenote")


def test_version_falls_back_when_metadata_missing(monkeypatch):
    """Running from a checkout that was never pip-installed still reports."""
    import importlib.metadata as metadata

    def boom(name):
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "version", boom)

    import sidenote

    assert cli._version() == sidenote.__version__


def test_version_is_a_flag_not_a_subcommand(monkeypatch, capsys):
    """`sidenote version` was removed - `--version` is the only spelling."""
    assert "version" not in [name for name, _ in cli.COMMANDS]
    assert not hasattr(cli, "version")

    monkeypatch.setattr(sys, "argv", ["sidenote", "version"])
    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_version_flag_exits_zero(monkeypatch, capsys):
    """`sidenote --version` follows the argparse convention: print and exit 0."""
    monkeypatch.setattr(sys, "argv", ["sidenote", "--version"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    assert cli._version() in capsys.readouterr().out


def test_short_version_flag_works(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["sidenote", "-V"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    assert cli._version() in capsys.readouterr().out


def test_status_includes_version(isolated_lock, monkeypatch, capsys):
    monkeypatch.setattr(cli.lockfile, "running_pid", lambda *a, **k: None)
    cli.status()
    assert cli._version() in capsys.readouterr().out


def test_source_version_matches_pyproject():
    """__init__.py and pyproject.toml must not drift apart.

    Compared against the source pyproject rather than installed metadata, so
    this doesn't fail spuriously between a version bump and a reinstall.
    """
    tomllib = pytest.importorskip("tomllib")

    import sidenote

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.exists():
        pytest.skip("running outside a source checkout")

    with open(pyproject, "rb") as handle:
        declared = tomllib.load(handle)["project"]["version"]

    assert sidenote.__version__ == declared


# ----------------------------------------------------------------- upgrade


def test_upgrade_hands_off_to_detached_helper(isolated_lock, monkeypatch, capsys):
    """pip must not run in-process.

    Windows locks a running .exe against overwrite and rename alike, so pip
    cannot replace Scripts/sidenote.exe while `sidenote upgrade` is that very
    process. The work is handed to a helper that waits for us to exit.
    """
    launched = []
    monkeypatch.setattr(cli, "_is_editable_install", lambda: False)
    monkeypatch.setattr(cli.lockfile, "running_pid", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_installed_version", lambda: "1.2.0")
    monkeypatch.setattr(
        cli.subprocess, "Popen", lambda cmd, **kw: launched.append((cmd, kw))
    )

    cli.upgrade()

    assert len(launched) == 1, "expected exactly one helper process"
    cmd, kwargs = launched[0]
    assert cmd[1:3] == ["-m", "sidenote._upgrade"]
    assert cmd[3] == str(os.getpid())
    assert kwargs["creationflags"] == cli.subprocess.CREATE_NEW_CONSOLE
    assert not any("pip" in str(part) for part in cmd)


def test_upgrade_stops_running_overlay_first(isolated_lock, monkeypatch, capsys):
    stopped = []
    monkeypatch.setattr(cli, "_is_editable_install", lambda: False)
    monkeypatch.setattr(cli.lockfile, "running_pid", lambda *a, **k: 4242)
    monkeypatch.setattr(cli.lockfile, "terminate", lambda pid, **k: True)
    monkeypatch.setattr(cli, "_installed_version", lambda: "1.2.0")
    monkeypatch.setattr(cli.subprocess, "Popen", lambda cmd, **kw: stopped.append(cmd))

    cli.upgrade()

    assert "stopping the running overlay" in capsys.readouterr().out.lower()


def test_upgrade_refuses_on_editable_install(isolated_lock, monkeypatch, capsys):
    """Upgrading an editable clone from PyPI would clobber the working copy."""
    launched = []
    monkeypatch.setattr(cli, "_is_editable_install", lambda: True)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **k: launched.append(a))

    cli.upgrade()

    assert launched == []
    out = capsys.readouterr().out.lower()
    assert "editable install" in out
    assert "git pull" in out


def test_upgrade_reports_helper_launch_failure(isolated_lock, monkeypatch):
    monkeypatch.setattr(cli, "_is_editable_install", lambda: False)
    monkeypatch.setattr(cli.lockfile, "running_pid", lambda *a, **k: None)
    monkeypatch.setattr(cli, "_installed_version", lambda: "1.2.0")

    def boom(*a, **k):
        raise OSError("no such file")

    monkeypatch.setattr(cli.subprocess, "Popen", boom)

    with pytest.raises(SystemExit) as excinfo:
        cli.upgrade()
    assert excinfo.value.code == 1


@pytest.mark.parametrize(
    "argument,expected",
    [
        ("stop", "stop"),
        ("status", "status"),
        ("upgrade", "upgrade"),
        ("init", "init"),
        ("start", "start"),
        (None, "start"),
    ],
)
def test_main_dispatches_to_the_right_command(argument, expected, monkeypatch):
    called = []
    for name, _ in cli.COMMANDS:
        monkeypatch.setattr(cli, name, lambda n=name: called.append(n))

    argv = ["sidenote"] + ([argument] if argument else [])
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()

    assert called == [expected]


# -------------------------------------------------------------------- init


def _profile(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "Documents" / "PowerShell").mkdir(parents=True)
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: home))
    return home / "Documents" / "PowerShell" / "profile.ps1"


def test_init_writes_functions_not_aliases(tmp_path, monkeypatch, capsys):
    """Set-Alias cannot carry arguments, so stop-note used to *start* the app."""
    profile = _profile(tmp_path, monkeypatch)

    cli.init()

    content = profile.read_text(encoding="utf-8")
    assert "function stop-note" in content
    assert "sidenote stop" in content
    assert "Set-Alias" not in content


def test_init_is_idempotent(tmp_path, monkeypatch, capsys):
    profile = _profile(tmp_path, monkeypatch)

    cli.init()
    first = profile.read_text(encoding="utf-8")
    cli.init()

    assert profile.read_text(encoding="utf-8") == first
    assert "already configured" in capsys.readouterr().out.lower()


def test_init_flags_the_old_broken_alias_block(tmp_path, monkeypatch, capsys):
    """Users who ran the old init have a stop-note that starts the overlay."""
    profile = _profile(tmp_path, monkeypatch)
    profile.write_text(
        "\n# CLI Sidenote Aliases\n"
        "Set-Alias -Name start-note -Value sidenote\n"
        "Set-Alias -Name stop-note -Value sidenote\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.init()

    assert excinfo.value.code == 1
    assert "old broken aliases" in capsys.readouterr().out.lower()


def test_init_recognises_the_pre_rename_marker(tmp_path, monkeypatch, capsys):
    """Profiles written before the cli-sidenote -> sidenote rename must not
    get a second block appended."""
    profile = _profile(tmp_path, monkeypatch)
    profile.write_text(
        "\n# CLI Sidenote\nfunction start-note { sidenote }\n"
        "function stop-note  { sidenote stop }\n",
        encoding="utf-8",
    )
    before = profile.read_text(encoding="utf-8")

    cli.init()

    assert profile.read_text(encoding="utf-8") == before
    assert "already configured" in capsys.readouterr().out.lower()


def test_init_preserves_existing_profile_content(tmp_path, monkeypatch):
    profile = _profile(tmp_path, monkeypatch)
    profile.write_text("# my important settings\n$env:FOO = 'bar'\n", encoding="utf-8")

    cli.init()

    content = profile.read_text(encoding="utf-8")
    assert "# my important settings" in content
    assert "$env:FOO = 'bar'" in content
    assert "function stop-note" in content
