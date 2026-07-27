# CLI Sidenote

> A lightweight, ADHD-friendly todo list that lives right next to your terminal window

![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Python](https://img.shields.io/badge/python-3.7+-green)
![License](https://img.shields.io/badge/license-MIT-blue)
[![PyPI](https://img.shields.io/pypi/v/cli-sidenote)](https://pypi.org/project/cli-sidenote/)

## Why This Exists

**The ADHD Problem**: You're coding in your terminal, a task pops into your head, and by the time you open Notepad/Tudo/a new tab, it's gone. That 2-second context switch is enough for ADHD brains to lose the thought entirely.

Every other tool costs you that switch - open an app, run a command, find the
window. CLI Sidenote is *already there*, docked to your terminal. `Shift+Tab`, type, `Enter`. Three seconds, without ever looking away from what you were doing.

### Why not existing tools

**Notepad/Heavy apps**: Requires Alt+Tab, finding the window, clicking - thought is gone
**Tudo/Tuxedo/Rondo**: Need to run a command, switch context, navigate UI - thought is gone
**PowerShell scratchpad**: Need to open it, switch focus - thought is gone
**Other terminal UIs**: Require launching a separate app or command - thought is gone

## Features

This isn't about rich features but simplicity. It's about **zero-friction capture**. When you have ADHD, the best todo app is the one that's already open and doesn't make you think.

| Feature | Description |
| :--- | :--- |
| **Terminal Integration** | Attaches flush to your terminal window, pixel-aligned |
| **Smart Z-Order Sync** | When you click the terminal, todo comes forward with it |
| **Movement Following** | Hides while you drag the terminal, snaps back when you stop |
| **Check Things Off** | Double-click a todo to complete it, don't just delete it |
| **Persistent Storage** | Todos saved atomically, survive reboots and crashes |
| **Global Hotkey** | `Shift+Tab` toggles from anywhere |
| **Lock to Terminal** | Lock button (🔓/🔒) to stick to a specific terminal |
| **Built-in Help** | `?` button lists every action, no need to memorise anything |
| **Timestamps** | Each todo gets a timestamp when added |
| **Dark Theme** | Minimal interface that matches terminal aesthetics |
| **Light Footprint** | Python plus two small libraries; event-driven, so it idles at ~0% CPU |

## Install

```powershell
pip install cli-sidenote
sidenote
sidenote init 
```

That's it - `Shift+Tab` toggles it from anywhere.

Optionally, `sidenote init` adds `start-note` / `stop-note` shortcuts to your
PowerShell profile.

> If `sidenote` isn't found after installing, your Python Scripts folder isn't on
> PATH - see [Troubleshooting](https://github.com/lyellr88/cli-sidenote/blob/main/DOCS.md#troubleshooting).

## Usage

**Add** - type in the box, press `Enter`. Timestamped automatically.
**Check off** - double-click a todo. It greys out and shows `[x]`. Double-click again to uncheck.
**Remove** - select it and press `Delete`.

The `?` button in the top-left lists every action, so there's nothing to memorise.

### Hotkeys

| Key | Action |
|-----|--------|
| `Shift+Tab` | Toggle overlay (works from any app) |
| `Enter` | Add todo |
| `Double-click` | Check off / uncheck |
| `Space` | Check off / uncheck the selected todo |
| `Delete` / `Backspace` | Remove selected todo |
| `Ctrl+Delete` | Clear all checked-off todos |
| `Escape` | Hide overlay |
| 🔓 / 🔒 | Pin to one specific terminal |

### Commands

| Command | Description |
|---------|-------------|
| `sidenote` | Start the overlay |
| `sidenote stop` | Stop it |
| `sidenote status` | Is it running? Shows version and PID |
| `sidenote --version` | Print the version (`-V` works too) |
| `sidenote --help` | List every command (`-h` works too) |
| `sidenote upgrade` | Update to the newest release |
| `sidenote init` | Add PowerShell shortcuts |

`sidenote stop` only ever terminates its own process - your dev servers,
notebooks, and training runs are never touched.

## Requirements

Windows 10/11, Python 3.7+, and a terminal (PowerShell, CMD, or Windows Terminal). Pulls in two small libraries: `keyboard` and `pywin32`.

## Documentation

**[Full documentation →](https://github.com/lyellr88/cli-sidenote/blob/main/DOCS.md)**

FAQ · Troubleshooting · How it works · Data format · Upgrading · Uninstalling · Development

## Contributing

Happy to take PRs for bug fixes, better terminal detection, performance, or
cross-platform support. Run `pytest` first, and add a test if you're fixing a bug. See [CONTRIBUTING.md](https://github.com/lyellr88/cli-sidenote/blob/main/CONTRIBUTING.md).

## License

MIT - do whatever you want with it.

---

Built by a developer with ADHD, for developers with ADHD. If this resonates, you get it. If it looks like overkill, it's not for you and that's fine. 🧠⚡
