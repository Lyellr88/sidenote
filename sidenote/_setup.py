"""Windows command discovery setup for the existing init command."""

import ctypes
import os
import sys
import sysconfig
import winreg
from importlib import metadata
from pathlib import Path

import pywintypes
import win32gui


def _scripts_dir():
    try:
        distribution = metadata.distribution("sidenote")
        for file in distribution.files or ():
            if file.name.lower() == "sidenote.exe":
                launcher = Path(distribution.locate_file(file))
                if launcher.is_file():
                    return launcher.resolve().parent
    except metadata.PackageNotFoundError:
        pass
    for scripts_path in (
        sysconfig.get_path("scripts"),
        sysconfig.get_path("scripts", scheme="nt_user"),
    ):
        scripts = Path(scripts_path)
        if (scripts / "sidenote.exe").is_file():
            return scripts.resolve()
    raise FileNotFoundError(
        "Could not find sidenote.exe. Reinstall with "
        "python -m pip install --force-reinstall sidenote."
    )


def ensure_user_path():
    """Return setup feedback without copying the merged process PATH."""
    if sys.prefix != sys.base_prefix:
        return "Virtual environment: keep it activated to use sidenote."

    scripts = _scripts_dir()
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        "Environment",
        0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
    ) as key:
        try:
            value, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            value, kind = "", winreg.REG_EXPAND_SZ
        if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
            raise OSError("User PATH is not a string; it was left unchanged.")
        for entry in value.split(";"):
            entry = entry.strip().strip('"')
            if kind == winreg.REG_EXPAND_SZ:
                entry = os.path.expandvars(entry)
            if entry and os.path.normcase(os.path.normpath(entry)) == os.path.normcase(
                str(scripts)
            ):
                return "Sidenote's Scripts folder is already on your user PATH."
        separator = ";" if value and not value.endswith(";") else ""
        winreg.SetValueEx(key, "Path", 0, kind, value + separator + str(scripts))

    environment = ctypes.create_unicode_buffer("Environment")
    try:
        win32gui.SendMessageTimeout(
            0xFFFF, 0x001A, 0, ctypes.addressof(environment), 0x0002, 1000
        )
    except (pywintypes.error, OSError):
        return "PATH saved. Sign out and back in if new terminals cannot find it."
    return f"Added to your user PATH: {scripts}"
