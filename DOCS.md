# Sidenote - Full Documentation

Everything beyond the basics. For getting started, see the [README](README.md).

- [FAQ](#faq)
- [Troubleshooting](#troubleshooting)
- [How It Works](#how-it-works)
- [Data Storage](#data-storage)
- [Upgrading](#upgrading)
- [Uninstalling](#uninstalling)
- [Development](#development)
- [Pro Tips](#pro-tips)

---

## FAQ

**Does it work on macOS or Linux?**

No - Windows only. Positioning and focus tracking are built directly on Win32 APIs (`SetWinEventHook`, DWM frame bounds), which have no cross-platform equivalent. A port would mean rewriting that layer per platform. PRs welcome.

**Does `Shift+Tab` still work normally in other apps?**

Yes, and that's deliberate. The hotkey doesn't swallow the keypress, so `Shift+Tab` still outdents in your editor and still tab-navigates backwards - the overlay toggles *in addition*. Suppressing it globally would break reverse-tab navigation everywhere, which is a much worse trade than an occasional double-action.

**Does it work with the VS Code integrated terminal?**

The hotkey works from anywhere, including VS Code. But the overlay attaches to *terminal windows*, and VS Code's integrated terminal belongs to `Code.exe`, not to `WindowsTerminal.exe` or `powershell.exe` - so the overlay won't dock to it. It docks to a real terminal window if one is open.

**Where are my todos stored?**

`~/.terminal_todos.json` (that's `C:\Users\<you>\.terminal_todos.json`). Plain JSON - back it up, sync it, edit it by hand if you like.

**Does it phone home?**

No. The only network access in the entire package is `sidenote upgrade`, which calls pip. Nothing is sent anywhere.

**Can I resize the overlay?**

Yes - drag its edge. It opens at 280px (scaled for your display's DPI), and a width you set by dragging is kept from then on, including when the terminal moves or resizes. The width resets to the default next time you start it.

Height isn't adjustable: it tracks your terminal's height so the two stay flush. You can also drag the overlay away from the terminal by its title bar to place it manually; the lock button re-attaches it.

**Can I have more than one list?**

Yes - up to 5 tabs. Click `+` in the top-left to add one; the entry field switches to naming mode, so type a name and press `Enter`. Switch tabs with the numbered buttons that appear next to `+`, and double-click a tab's name in the footer to rename it. A `×` appears next to the name once you have a second tab; it asks you to confirm before deleting that tab and everything in it.

**Can I reorder my todos?**

Yes - press and drag a todo up or down in the list to move it.

**I deleted a todo by accident. Can I get it back?**

Press `Ctrl+Z`. It restores the list to how it looked before your last delete (a single one or a `Ctrl+Delete` clear), on whichever tab it happened on.

**Why does it vanish while I drag the terminal?**

Deliberate. Repositioning it on every frame of a drag looks broken, so it hides on `MOVESIZESTART` and reappears, correctly placed, on `MOVESIZEEND`.

**I have several terminals open. Which one does it pick?**

The focused one if it's a terminal, otherwise the topmost. Click the 🔓 lock button to pin it to one specific terminal and stop it following the others.

**Does it need administrator rights?**

No. One caveat: the global hotkey can't see keystrokes sent to windows running *as administrator* unless the overlay is elevated too. That's a Windows security boundary, not something the app can work around.

**Why Python and tkinter?**

Because it was built in an hour to solve one person's problem, and tkinter ships with Python. It idles at roughly 0% CPU because it's event-driven rather than polling, so there's little to gain from a rewrite.

---

## Troubleshooting

**`sidenote` command not found after installation**

Your Python Scripts folder isn't on PATH. Find it:

```powershell
python -c "import site; print(site.USER_BASE + '\\Scripts')"
```

Then add it to your user PATH:

```powershell
$scripts = python -c "import site; print(site.USER_BASE + '\\Scripts')"
$user = [Environment]::GetEnvironmentVariable('PATH','User')
[Environment]::SetEnvironmentVariable('PATH', "$user;$scripts", 'User')
```

Close and reopen your terminal afterwards.

> Read the `User` scope as shown above rather than using `setx PATH "$env:PATH;..."`.
> `$env:PATH` is the *merged* system and user PATH, so that form permanently
> copies your entire system PATH into your user PATH, and `setx` truncates
> anything past 1024 characters.

**`start-note` / `stop-note` not found**

Reload your profile with `. $PROFILE`, or open a new PowerShell window. If they still aren't there, run `sidenote init`.

**Overlay doesn't appear**

- Make sure a terminal window is actually open - it docks to one
- Check it's running: `sidenote status`
- Restart it: `sidenote stop` then `sidenote`

**Overlay doesn't come forward with the terminal**

Click directly on the terminal window; it reacts to the focus event immediately. If you're clicking from another app, that app gets focus first.

**"Terminal overlay is already running!" but nothing is on screen**

`sidenote status` reports whether a real process holds the lock. Stale locks are detected and reclaimed automatically, so this normally resolves itself; if not, `sidenote stop` clears it.

**Hotkey not working**

- Confirm it's running: `sidenote status`
- The status bar shows an error if the hotkey failed to register
- It can't capture input from elevated windows unless it's elevated too

**Todos not saving**

The status bar at the bottom of the overlay shows the reason - usually permissions or a full disk.

**Upgrade fails with "Access is denied"**

Close any other terminal that's running a `sidenote` command and try again. Windows locks a running executable, and pip can't replace a file that's in use.

**`sidenote upgrade` says "Upgrade complete" but `sidenote --version` hasn't changed**

Check the upgrade window's output for `Requirement already satisfied` next to every package. That means pip trusted its local cache instead of checking PyPI, so it saw nothing to do and exited without error - `sidenote upgrade` reports that as success because pip itself reported success. Run the manual command above with `--no-cache-dir` to force a real check.

---

## How It Works

The overlay uses Windows API calls to:

1. **Detect terminals** - Identifies windows by the *executable* behind them (`WindowsTerminal.exe`, `powershell.exe`, `pwsh.exe`, `cmd.exe`, ...) rather than by window title, so a browser tab named "PowerShell docs" isn't mistaken for a terminal. DWM-cloaked windows are excluded.
2. **Position itself** - Aligns flush to the right edge using DWM's extended frame bounds. `GetWindowRect` includes Windows' invisible ~8px resize border, which would leave a visible gap. Window chrome is measured at runtime, so it's correct at any DPI.
3. **Sync z-order** - When the terminal takes focus, briefly flashes topmost with `SWP_NOACTIVATE` to bring the overlay forward, without becoming permanently always-on-top and without stealing your keyboard focus.
4. **Follow movement** - Subscribes to `SetWinEventHook` for move/resize/minimise/destroy events instead of polling, so it reacts instantly and costs nothing while idle. Repositioning keeps a width you set by dragging, and only recomputes the default one.
5. **Persist data** - Saves to `~/.terminal_todos.json` with an atomic write-and-rename, so an interrupted save can't corrupt the file.

**Threading note:** tkinter is not thread-safe. Window events arrive on a Win32 hook thread and the hotkey arrives on the `keyboard` library's thread; both hand work to the main thread through a queue rather than touching widgets directly.

**Project layout:**

| Path | Purpose |
|------|---------|
| `sidenote/terminal_overlay.py` | tkinter UI, positioning, event handling |
| `sidenote/winutil.py` | Terminal detection, DPI, Win32 event hooks |
| `sidenote/storage.py` | Loading and atomically saving todos |
| `sidenote/lockfile.py` | PID-based single-instance lock |
| `sidenote/cli.py` | The `sidenote` command |
| `sidenote/_upgrade.py` | Detached helper for `sidenote upgrade` |
| `tests/` | pytest suite |
| `setup.ps1` | One-step setup for a cloned repo |

---

## Data Storage

Todos live in `~/.terminal_todos.json`, grouped into tabs:

```json
{
  "version": 3,
  "active_tab": 0,
  "tabs": [
    {
      "name": "Tab 1",
      "todos": [
        { "text": "Fix the login bug",    "created": "2026-07-27T14:23:00", "done": true  },
        { "text": "Update documentation", "created": "2026-07-27T14:25:00", "done": false }
      ]
    }
  ]
}
```

Writes go to a temporary file and are then renamed into place, so an interrupted save can't leave you with a truncated todo list. Files written by earlier versions (a flat `todos` list, or 1.0.x's flat list of `"[14:23] do the thing"` strings) are migrated into a single tab the first time they're loaded.

---

## Upgrading

```powershell
sidenote upgrade
```

It stops the overlay if it's running, then opens a small window that performs the update and reports the result. Run `sidenote` afterwards to start the new version.

**Why a separate window?** Windows locks a running program's `.exe`, and `sidenote.exe` is what you just ran - pip can't replace a file that's in use, and would fail with "Access is denied". The helper waits for the command to exit first.

**Your todos are safe.** They live outside the package and are never touched by pip.

The manual equivalent:

```powershell
sidenote stop
python -m pip install --upgrade --no-cache-dir sidenote
```

`--no-cache-dir` matters here: without it, pip can trust locally cached metadata and report "Requirement already satisfied" for a version that's no longer the latest, instead of fetching the new release.

If you installed from a clone, `sidenote upgrade` will say so and stop, since pulling from PyPI would overwrite your working copy. Use git instead:

```powershell
sidenote stop
git pull
pip install -e .    # only needed if dependencies changed
```

---

## Uninstalling

```powershell
sidenote stop
pip uninstall sidenote
```

That removes the package and the `sidenote` command, but deliberately leaves your data and shell config alone. To remove those too:

```powershell
Remove-Item "$env:USERPROFILE\.terminal_todos.json" -ErrorAction SilentlyContinue
Remove-Item "$env:USERPROFILE\.terminal_overlay.lock" -ErrorAction SilentlyContinue

notepad $PROFILE.CurrentUserAllHosts    # delete the "# Sidenote" block
```

The block to delete looks like this:

```powershell
# Sidenote
function start-note { sidenote }
function stop-note  { sidenote stop }
```

Nothing else is written anywhere - no registry keys, no scheduled tasks, no files outside your home directory. If you added a Startup-folder shortcut, remove that too.

---

## Development

```powershell
git clone https://github.com/lyellr88/sidenote.git
cd sidenote
pip install -e ".[dev]"
pytest
```

The suite covers storage, the PID lock's liveness and PID-reuse handling, window-detection invariants, CLI behaviour, and - via `tests/test_overlay_smoke.py` - the tkinter overlay itself, driven headlessly. A small manual checklist in [AGENTS.md](AGENTS.md) covers what that doesn't reach, and documents the invariants that are easy to break by accident.

A GitHub Actions workflow runs the suite on every push to `master` and publishes to PyPI on success; see [AGENTS.md](AGENTS.md#ci).

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR.

---

## Pro Tips

**Auto-start on login** - Press `Win+R`, run `shell:startup`, and drop a shortcut to `sidenote.exe` in there. Find it with `(Get-Command sidenote).Source`.
**Multiple terminals** - Use the 🔓 lock button to pin it to one terminal.
**Separate lists** - Use tabs to split work from personal, or one project from another.
**Muscle memory** - `Shift+Tab` uses the same hand position as `Tab`.
**Quick capture** - `Shift+Tab` → type → `Enter` → `Shift+Tab`. Three seconds.
**Clean slate** - `Ctrl+Delete` clears everything checked off, or delete `~/.terminal_todos.json` to wipe all todos.
