# Sidenote - Agent Instructions

Instructions for AI coding agents working on this repo. Keep changes minimal and focused.

## Architecture

Sidenote is a Python-based terminal overlay for Windows: a todo list that attaches to your terminal window.

**Core Files:**

- `sidenote/terminal_overlay.py` - tkinter UI, positioning, and event handling
- `sidenote/winutil.py` - Terminal detection, DPI handling, Win32 event hooks
- `sidenote/storage.py` - Load / migrate / atomically save todos
- `sidenote/lockfile.py` - PID-based single-instance lock
- `sidenote/cli.py` - Entry point for `sidenote` (start/stop/status/upgrade/init)
- `sidenote/_upgrade.py` - Detached helper process for `sidenote upgrade`
- `sidenote/__main__.py` - Enables `pythonw -m sidenote`
- `sidenote/__init__.py` - Package metadata
- `pyproject.toml` - Package configuration for PyPI
- `tests/` - pytest suite
- `setup.ps1` - Local setup script (for cloned repo use)

There is exactly one copy of the application code, inside `sidenote/`. A duplicate `terminal_overlay.py` used to sit at the repo root; do not reintroduce it.

**Key Features:**

- Terminal window detection (PowerShell, CMD, Windows Terminal)
- Right-side positioning that follows terminal movement
- Z-order synchronization (todo comes forward when terminal gets focus)
- Global hotkey (`Shift+Tab`) to toggle visibility
- Check todos off (double-click / `Space`); `Ctrl+Delete` clears completed
- Right-click a todo to copy its text, acknowledged by a colour fade
- Drag a todo to reorder it within its tab
- Up to 5 tabs, each a separate todo list, added/renamed/switched/deleted from the header and footer, with a confirmation popup before deletion
- `Ctrl+Z` undoes the last delete (single or `Ctrl+Delete` batch), per tab
- Width is user-resizable by dragging; height stays matched to the terminal
- `?` button showing all quick actions
- Lock button to stick to one specific terminal
- Persistent storage at `~/.terminal_todos.json`

## Code Patterns

**Threading (read this before touching the UI):**
tkinter is not thread-safe. The Win32 hook thread and the `keyboard` hotkey thread must never touch a widget. Both call `TerminalOverlay._post(fn)`, which queues the callable; the main thread drains it in `_pump()` via `after()`. Calling `root.withdraw()` or `.config()` from a background thread causes intermittent hangs and crashes - this was a real bug, not a theoretical one.

**Window Detection:**
`winutil.is_terminal()` resolves each hwnd to its owning executable via `GetWindowThreadProcessId` + `QueryFullProcessImageNameW` and matches against `winutil.TERMINAL_EXES`. Do not match on window titles: a browser tab named "PowerShell docs" passes a title check. Cloaked (hidden UWP) windows are excluded.

**Z-Order Sync:**
On `EVENT_SYSTEM_FOREGROUND` for the terminal, `winutil.bring_to_front()` flashes `HWND_TOPMOST` → `HWND_NOTOPMOST` with `SWP_NOACTIVATE`, raising the overlay without permanent always-on-top behaviour and without stealing keyboard focus.

**Movement Detection:**
Event-driven via `SetWinEventHook` (`MOVESIZESTART/END`, `LOCATIONCHANGE`, `MINIMIZESTART/END`, `DESTROY`) on a dedicated thread with its own message pump. A 2-second fallback poll only covers terminals opening and closing. Do not reintroduce a tight position-polling loop.

**Positioning:**
Uses DWM extended frame bounds (`winutil.visible_rect`), not `GetWindowRect`, which includes an invisible ~8px resize border. Chrome height is measured via `winutil.window_metrics`, never hardcoded - a hardcoded 31px title bar broke on scaled displays.

`position_next_to_terminal()` runs on every terminal event, so it must not recompute width unconditionally - that snapped a user-resized overlay back to `BASE_WIDTH` within milliseconds. `_on_configure` records any width that differs from the one we applied (`_applied_w`) as `_user_width`, and positioning honours it. A user width is already a client width, so it must not have `chrome_w` subtracted a second time.

**Listbox Colours:**
Tk draws the *selected* row with `selectforeground`, ignoring per-item `fg`. Any per-item colour must set both, or it silently does nothing while the row is highlighted - this hid the copy flash and made completed todos look incomplete when selected. Note that `itemcget(i, "fg")` echoes what you set, not what is rendered, so it cannot confirm this.

**Tabs and the `self.todos` alias:**
`self.todos` is not a copy - it *is* `self.tabs[self.active_tab]["todos"]`, the same list object. Every mutation (`add_todo`, `remove_todo`, drag-reorder, undo) uses in-place operations (`.append`, `del ...[i]`, `[:]  = ...`, `.pop`/`.insert`) so the alias stays valid without an explicit sync step. A plain `self.todos = new_list` rebind breaks it silently - `clear_done` had this bug during development; it must slice-assign (`self.todos[:] = remaining`). `_switch_tab` is the only place allowed to rebind, since it's deliberately pointing at a different tab's list.

**Deleting a tab and the undo stack:**
`_undo_stack` entries are `(tab_index, snapshot)` pairs, so removing a tab (`_delete_tab`) has to walk the stack: drop entries pointing at the deleted tab, and shift down by one every index greater than it. Skipping this leaves stale entries that either restore into the wrong tab after later tabs shift, or reference an index that no longer exists. `_confirm_delete_tab` captures the target tab's index in a closure rather than reading `self.active_tab` again inside the confirm callback, since the active tab could change while the popup is open.

`storage.MAX_TABS` (5) exists because the tab-switcher buttons live in the header next to the centred "Sidenote" title - past 5 tabs the button row can reach far enough right to overlap the title on the default 280px width. Widening this cap means re-measuring that overlap (see `_render_tabs`'s tight `padx=2`), not just bumping the constant.

**Entry field modes:**
The single entry field is reused for three things - `self._entry_mode` is `"todo"`, `"new_tab"`, or `"rename_tab"`, and `_on_entry_return`/`_on_entry_escape` dispatch on it. `start_new_tab()`/`start_rename_tab()` prime the field (pre-filled text, selected, a blue `ACCENT` focus ring) and `_leave_entry_mode()` always clears both the mode and the ring - a naming step left half-finished must not leak into a later plain todo add.

**Storage:**
`{"version": 3, "active_tab": int, "tabs": [{"name", "todos": [{"text", "created", "done"}]}]}` at `~/.terminal_todos.json`. Saves are atomic (temp file + `os.replace`). Pre-tabs files (a flat `todos` list, schema 2, or 1.0.x's flat list of `"[14:23] Fix bug"` strings) are migrated into a single tab on load; keep that path working. `storage.load()` never returns an empty tab list, so callers can always index `tabs[active_tab]`. `storage.save()` returns an error string rather than raising or swallowing - surface it in the status bar.

**Process Management:**
Never kill by image name. `taskkill /F /IM python.exe` killed every Python process on the user's machine. Terminate only the PID in `~/.terminal_overlay.lock`, and validate it is both alive and a Python process before trusting it (`lockfile.is_overlay_pid`).

**Console Output:**
Route CLI prints through `cli._say()`. Bare `print("✓")` raises `UnicodeEncodeError` under cp1252, still the default in cmd.exe.

**Self-Upgrade:**
`cli.upgrade()` must never run pip in-process. Windows locks a running `.exe` against overwrite *and* rename (verified: `WinError 32` for both), so pip cannot replace `Scripts/sidenote.exe` while `sidenote upgrade` is the running process. `sidenote/_upgrade.py` is spawned with `CREATE_NEW_CONSOLE`, waits on the parent PID via `WaitForSingleObject`, and only then runs pip. That helper may import stdlib only, all at module level - pip is rewriting this package's files while it runs, so a lazy import could load a half-written module. Editable installs are refused, since upgrading them from PyPI would replace the user's working copy.

## Consistency Rules

**When changing the package version, update:**

1. `pyproject.toml` - `version` field
2. `sidenote/__init__.py` - `__version__`
3. `README.md` - Title if major version changes

`test_source_version_matches_pyproject` fails if 1 and 2 drift apart. Published versions are immutable on PyPI, so any change after a release needs a new number. `cli._version()` reads installed metadata first and falls back to `__version__` for source checkouts that were never pip-installed.

**Documentation split:**
`README.md` is the short front page and is what PyPI renders - keep it lean. Everything else (FAQ, troubleshooting, internals, upgrade/uninstall detail, dev setup) lives in `DOCS.md`. Links from `README.md` to other repo files **must be absolute GitHub URLs**: relative links resolve against pypi.org and 404 there.

**When adding new commands, update:**

1. `sidenote/cli.py` - add the handler, an entry in the `COMMANDS` list, and a key in `main()`'s `dispatch` dict
2. `README.md` - Commands table
3. `DOCS.md` - If it needs more than one line of explanation
4. `tests/test_cli.py` - Cover the new behaviour
5. Test the command after `pip install -e .`

`COMMANDS` is the single source of truth: the `--help` listing and argparse's `choices` are both derived from it, and `test_command_list_matches_dispatch` fails if an entry has no dispatch handler. Help output is hand-rolled in `_format_help()` because argparse renders a `choices` positional as a cramped `{a,b,c}` blob with one shared description. Keep every label shorter than `_GUTTER` and every line under 80 columns - both are enforced by tests.

**When adding new keybindings, update:**

1. `sidenote/terminal_overlay.py` - the binding *and* the `HELP_ROWS` table that populates the `?` panel
2. `README.md` - Hotkeys table
3. The manual checklist above

**When changing the storage format:**

1. Bump `storage.SCHEMA_VERSION`
2. Keep the existing migration path working - users have live data
3. Add a migration test to `tests/test_storage.py`

## Testing

Automated suite (run this before every commit):

```powershell
pip install -e ".[dev]"
pytest
```

`tests/` covers storage migration and atomic saves, lock-file liveness and PID-reuse handling, window-detection invariants, and CLI behaviour. Several tests are explicit regression guards - `test_terminate_kills_only_the_target`, `test_stale_lock_is_cleared_not_honoured`, `test_init_writes_functions_not_aliases`

- so if you change that behaviour, understand the bug being guarded first.

Tests that spawn real processes or enumerate live windows assert on invariants, not on specific machines. Keep them that way.

The tkinter UI has no automated coverage; verify by hand:

```powershell
sidenote         # Test start
sidenote status  # Test status
sidenote stop    # Test stop
sidenote init    # Test init
```

Manual checklist:

- ✅ Overlay appears flush against the terminal, no gap, matching height
- ✅ Follows terminal when moved, snapped, and maximised
- ✅ Comes forward when clicking terminal, without stealing keyboard focus
- ✅ `Shift+Tab` toggles visibility
- ✅ Double-click checks a todo off; `Ctrl+Delete` clears completed ones
- ✅ Right-click copies a todo and flashes it; the row returns to its normal colour
- ✅ The flash is visible on a row that is currently selected, not just unselected ones
- ✅ Dragging a todo up or down moves it, and the new order survives a restart
- ✅ Dragging the edge wider survives clicking the terminal, moving it, and resizing it
- ✅ The list scrolls by wheel and by arrow keys, with no scrollbar visible
- ✅ `?` panel opens, closes, and stays on screen at the right screen edge
- ✅ `+` adds a tab, capped at 5; the entry field switches to naming mode and back
- ✅ Double-clicking the footer tab name renames it; `Escape` cancels a name in progress
- ✅ The numbered tab buttons switch lists, and don't overlap the "Sidenote" title at 5 tabs
- ✅ The footer `×` only appears with 2+ tabs; it asks for confirmation before deleting, and Cancel/Escape leave the tab alone; the keyboard Delete key confirms it, same as clicking the popup's Delete button
- ✅ Deleting a tab you weren't on doesn't happen - only the active tab's `×` is reachable
- ✅ `Ctrl+Delete` then `Ctrl+Z` restores the cleared todos; a single delete then `Ctrl+Z` restores that one
- ✅ Todos persist after restart, and a 1.0.x or pre-tabs (schema 2) file migrates cleanly
- ✅ Lock button works, and survives the locked terminal being closed
- ✅ Commands work from any directory
- ✅ Correct on a scaled (150%/200% DPI) display

## Workflow

- Keep changes small and focused
- Match existing code style (no major refactors)
- Test manually before publishing
- Update README for user-facing changes
