"""Init PATH setup with isolated registry and launcher discovery."""

import sys
from contextlib import nullcontext
from importlib.metadata import PackagePath
from types import SimpleNamespace

import pytest

from sidenote import _setup, cli


@pytest.fixture
def registry(tmp_path, monkeypatch):
    scripts = tmp_path / "Python With Spaces" / "Scripts"
    scripts.mkdir(parents=True)
    monkeypatch.setattr(_setup, "_scripts_dir", lambda: scripts)
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)
    state = {"value": r"%USERPROFILE%\Tools;C:\Existing;", "kind": 2, "writes": 0}
    monkeypatch.setattr(_setup.winreg, "CreateKeyEx", lambda *a: nullcontext(1))

    def query(*args):
        if state["value"] is None:
            raise FileNotFoundError
        return state["value"], state["kind"]

    def write(key, name, reserved, kind, value):
        state.update(value=value, kind=kind, writes=state["writes"] + 1)

    monkeypatch.setattr(_setup.winreg, "QueryValueEx", query)
    monkeypatch.setattr(_setup.winreg, "SetValueEx", write)
    monkeypatch.setattr(_setup.win32gui, "SendMessageTimeout", lambda *a: None)
    monkeypatch.setenv("PATH", r"C:\MachineOnly;C:\OtherPython")
    state["scripts"] = scripts
    return state


@pytest.mark.parametrize("kind", [1, 2])
def test_path_preserves_original_value_and_type(registry, kind):
    registry["kind"] = kind
    original = registry["value"]
    _setup.ensure_user_path()
    assert registry["value"] == original + str(registry["scripts"])
    assert registry["kind"] == kind
    assert "MachineOnly" not in registry["value"]
    _setup.ensure_user_path()
    assert registry["writes"] == 1


def test_path_creates_missing_user_value(registry):
    registry["value"] = None
    _setup.ensure_user_path()
    assert registry["value"] == str(registry["scripts"])
    assert registry["kind"] == _setup.winreg.REG_EXPAND_SZ


def test_path_recognises_expanded_quoted_case_variant(registry, monkeypatch):
    monkeypatch.setenv("SIDENOTE_TEST_ROOT", str(registry["scripts"].parent))
    registry["value"] = '"%SIDENOTE_TEST_ROOT%\\scripts\\"'
    _setup.ensure_user_path()
    assert registry["writes"] == 0


def test_path_keeps_separator_when_missing(registry):
    registry["value"] = r"C:\Existing"
    _setup.ensure_user_path()
    assert registry["value"] == "C:\\Existing;" + str(registry["scripts"])


def test_path_rejects_non_string_registry_type(registry):
    registry["kind"] = _setup.winreg.REG_DWORD
    with pytest.raises(OSError, match="left unchanged"):
        _setup.ensure_user_path()
    assert registry["writes"] == 0


def test_notification_failure_reports_saved_path(registry, monkeypatch):
    def fail(*args):
        raise OSError("notification timed out")

    monkeypatch.setattr(_setup.win32gui, "SendMessageTimeout", fail)
    assert "Sign out" in _setup.ensure_user_path()
    assert registry["writes"] == 1


def test_virtual_environment_does_not_persist_path(monkeypatch):
    monkeypatch.setattr(sys, "prefix", "isolated-venv")
    assert "activated" in _setup.ensure_user_path()


def test_init_repairs_path_with_existing_profile(registry, tmp_path, monkeypatch):
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    profile = tmp_path / "Documents" / "PowerShell" / "profile.ps1"
    profile.parent.mkdir(parents=True)
    original = cli.PROFILE_BLOCK + "\n# user settings\n"
    profile.write_text(original, encoding="utf-8")
    cli.init()
    assert registry["writes"] == 1
    assert str(registry["scripts"]) in registry["value"]
    assert profile.read_text(encoding="utf-8") == original


def test_scripts_dir_uses_installed_launcher_record(tmp_path, monkeypatch):
    launcher = tmp_path / "Actual Scripts" / "sidenote.exe"
    launcher.parent.mkdir()
    launcher.touch()
    distribution = SimpleNamespace(
        files=[PackagePath("../../Scripts/sidenote.exe")],
        locate_file=lambda file: launcher,
    )
    monkeypatch.setattr(_setup.metadata, "distribution", lambda name: distribution)
    assert _setup._scripts_dir() == launcher.parent


@pytest.mark.parametrize("user_install", [False, True])
def test_scripts_dir_falls_back_to_existing_launcher(
    tmp_path, monkeypatch, user_install
):
    normal, user = tmp_path / "Scripts", tmp_path / "User Scripts"
    target = user if user_install else normal
    target.mkdir()
    (target / "sidenote.exe").touch()
    monkeypatch.setattr(
        _setup.metadata, "distribution", lambda name: SimpleNamespace(files=None)
    )
    monkeypatch.setattr(
        _setup.sysconfig, "get_path", lambda name, **kw: user if kw else normal
    )
    assert _setup._scripts_dir() == target


def test_missing_launcher_is_not_added_to_path(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _setup.metadata, "distribution", lambda name: SimpleNamespace(files=None)
    )
    monkeypatch.setattr(_setup.sysconfig, "get_path", lambda *a, **kw: str(tmp_path))
    with pytest.raises(FileNotFoundError, match="Reinstall"):
        _setup._scripts_dir()


def test_init_reports_path_permission_failure_before_profile_edit(
    tmp_path, monkeypatch, capsys
):
    def fail():
        raise PermissionError("denied")

    monkeypatch.setattr(_setup, "ensure_user_path", fail)
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(SystemExit) as exc:
        cli.init()
    assert exc.value.code == 1
    assert "denied" in capsys.readouterr().out
    assert not (tmp_path / "Documents").exists()
