# Sidenote - Agent Instructions

Instructions for AI coding agents working on this repo. Keep changes minimal and focused.

## Architecture

Sidenote is a Python-based terminal overlay for Windows: a todo list that attaches to your terminal window.

**Core Files:**

- `sidenote/terminal_overlay.py` - `TerminalOverlay` itself: setup, cross-thread plumbing, the shared entry-field state machine, visibility, process lifecycle. See "Module Split" below for the rest of the class.
- `sidenote/overlay_ui.py` - Widget construction, the help panel, tooltips, the generic confirm popup, window dragging
- `sidenote/overlay_positioning.py` - Terminal window tracking, following, and the lock
- `sidenote/overlay_tabs.py` - Tab create/rename/switch/delete
- `sidenote/overlay_todos.py` - Todo add/edit/toggle/remove/reorder/undo, list rendering, persistence calls
- `sidenote/overlay_theme.py` - Colors, sizing constants, and `HELP_ROWS` - pure data, no behavior
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

**Module Split:**
`TerminalOverlay` was a single ~1050-line file; it's now `TerminalOverlay(OverlayUIMixin, PositioningMixin, TabsMixin, TodosMixin)` split across the five files above, purely by moving methods verbatim into mixin classes - no method was rewritten, renamed, or had its logic changed to make this split, and none of `self.`'s attribute access changed either, since a mixin's methods run against the same fully-composed instance regardless of which file defines them. Constants moved to `overlay_theme.py` because they're already shared across every one of those files, not because sharing was anticipated - see `problem-solving.md`/`refactor-middle-ground.md`.

Where a new method belongs: window chrome and dialogs → `overlay_ui.py`; anything about where the terminal is or where the overlay sits relative to it → `overlay_positioning.py`; tab CRUD → `overlay_tabs.py`; todo CRUD and list state → `overlay_todos.py`. The entry-field state machine (`_prime_entry`, `_leave_entry_mode`, `_on_entry_return`, `_on_entry_escape`) stays in `terminal_overlay.py` itself rather than in tabs or todos, since both of those already call into it - it's shared orchestration, not owned by either.

**Key Features:**

- Terminal window detection (PowerShell, CMD, Windows Terminal)
- Right-side positioning that follows terminal movement
- Z-order synchronization (todo comes forward when terminal gets focus)
- Global hotkey (`Shift+Tab`) to toggle visibility
- Check todos off (double-click / `Space`); `Ctrl+Delete` clears completed
- Right-click a todo to copy its text, acknowledged by a colour fade
- `Enter` on a selected todo edits its text in place
- Drag a todo to reorder it within its tab
- Up to 5 tabs, each a separate todo list, added/renamed/switched/deleted from the header and footer, with a confirmation popup before deletion
- `Ctrl+Z` undoes the last delete (single or `Ctrl+Delete` batch), per tab
- Width is user-resizable by dragging; height stays matched to the terminal
- `Ctrl+`/`Ctrl-` zooms the list and entry text between 7pt and 20pt; resets on restart
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
The single entry field is reused for four things - `self._entry_mode` is `"todo"`, `"new_tab"`, `"rename_tab"`, or `"edit_todo"`, and `_on_entry_return`/`_on_entry_escape` dispatch on it. `start_new_tab()`/`start_rename_tab()`/`start_edit_todo()` prime the field (pre-filled text, selected, a blue `ACCENT` focus ring) via `_prime_entry()`, and `_leave_entry_mode()` always clears the mode, the ring, and `self._edit_index` - a naming or editing step left half-finished must not leak into a later plain todo add. `start_edit_todo()` is bound to `<Return>` on the listbox itself, not the entry - the entry's own `<Return>` is already the commit key for whichever mode is active.

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

`test_source_version_matches_pyproject` fails if 1 and 2 drift apart, and the release workflow's preflight refuses a tag that disagrees with either. Published versions are immutable on PyPI, so any change after a release needs a new number. `cli._version()` reads installed metadata first and falls back to `__version__` for source checkouts that were never pip-installed.

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

`tests/test_overlay_smoke.py` covers the tkinter UI by instantiating a real `TerminalOverlay` headlessly and driving its actual methods - tabs, drag-reorder, undo, edit-in-place, the header-overlap regression at 5 tabs. Storage is redirected via `monkeypatch.setattr(storage, "load"/"save", ...)`, not the `DATA_FILE` attribute - `load`/`save`'s own default parameter is already bound to the real path at import time, so patching the attribute afterward wouldn't change it. Each test's fixture retries `TerminalOverlay()` on `TclError`: the background `WindowEventListener` thread it starts has no `stop()` and can still be unwinding when the next test's Tk interpreter is created, which occasionally raises a spurious error unrelated to anything under test.

That file covers logic, not real mouse/keyboard input - `event_generate` proved too timing-sensitive for things like double-clicks and popup keystrokes during development (works in isolation, fails depending on prior test timing in the same process) to trust in CI. Those are exercised by calling the bound method directly instead (e.g. `overlay.toggle_done()` rather than a synthetic double-click), which still runs the real production code. Manual verification is still worthwhile for anything the automated coverage doesn't reach:

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
- ✅ `Enter` on a selected todo loads it for editing; `Enter` again saves, `Escape` cancels without changing it
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
- ✅ `Ctrl+` / `Ctrl-` grows/shrinks list and entry text together, clamps at both ends, and works whether the entry or the list has focus
- ✅ Todos persist after restart, and a 1.0.x or pre-tabs (schema 2) file migrates cleanly
- ✅ Lock button works, and survives the locked terminal being closed
- ✅ Commands work from any directory
- ✅ Correct on a scaled (150%/200% DPI) display

## Workflow

- Keep changes small and focused
- Match existing code style (no major refactors)
- Test manually before publishing
- Update README for user-facing changes

## Linting

`pyproject.toml`'s `[tool.ruff.lint]` `select` is deliberate, not exhaustive - ruff has no config here by default, which means it runs with essentially every rule category enabled, including ones aimed at async libraries and web-service security auditing that don't fit a synchronous Windows desktop app. The list there is a standard baseline (`E`, `W`, `F`, `I`, `UP`, `B`, `C4`, `SIM`, `RUF`) plus three specific rules from noisier categories that turned out worth keeping once every finding they raised was actually checked, not just fixed on autopilot:

- **`BLE001`** (blind `except Exception`) - most sites narrow to the real exception type. Pywin32 calls (`win32gui.*`, `win32process.*`) raise `pywintypes.error`, not `OSError`; sites here catch `(pywintypes.error, OSError)` for margin against version differences, not because they're unsure what's really thrown. A few sites (the `WindowEventListener._dispatch` trampoline, `TerminalOverlay._pump`, the hotkey thread) stay broad on purpose - they're dispatching arbitrary callbacks from a background thread or a ctypes callback boundary, where the whole point is "catch anything so one bad callback doesn't take the thread down," and narrowing them would defeat that. Those carry a `# noqa: BLE001` plus a comment saying why, or use `contextlib.suppress(Exception)` where no exception detail is needed.
- **`PLR0402`** / **`PLW1510`** - `from importlib import metadata` over the aliased form, and explicit `check=False` on `subprocess.run()` calls that already branch on `.returncode`. Both are safe, mechanical, zero-behavior-change fixes.

`DTZ005`/`DTZ006` (naive `datetime.now()`) are not selected at all - `storage.py` stores and displays local wall-clock time on purpose (todos show as "14:23", not UTC), so timezone-aware timestamps would be a real behavior and data-format change, not a cleanup. `RUF001` is selected but `×` (the tab-delete and help-panel close glyph) is ignored project-wide in the `ignore` list, since it's a deliberate icon choice that would refire on every future close button, not a confusable-character typo.

When a new `except Exception:` shows up: check what the wrapped call can actually raise before choosing a narrower type or a `noqa`. A guess that happens to satisfy ruff but misses a real exception type is worse than the blind catch it replaced - it looks fixed and isn't.

## CI

`.github/workflows/ci.yml` runs on every pull request and every push to `master`. Jobs: `lint` (`ruff check .` on Python 3.13), `test` (`pytest` on Python 3.9 and 3.13), `lint-workflows` (actionlint), and `ci-ok`, which fails unless the other three succeeded. `ci-ok` is the single required status check in the branch ruleset, so do not rename it. Everything runs on `windows-latest` except actionlint and `ci-ok`, because the app needs pywin32, `keyboard`, and tkinter. CI no longer publishes anything.

`.github/workflows/release.yml` publishes, and only runs when a tag like `v1.5.0` is pushed. `preflight` checks the tag is semver, sits on `master`, and equals the version in **both** `pyproject.toml` and `sidenote/__init__.py` (a pre-release tag such as `v1.5.0-rc.1` is compared as `1.5.0rc1`, the PEP 440 spelling). It then builds the wheel and sdist, smoke-tests the wheel, attests build provenance, drafts the GitHub Release, publishes to PyPI through trusted publishing (environment `pypi`, no stored token), publishes the release, and checks PyPI serves the new version. Changes to either workflow are CI work: do not touch them for anything else.

The lint step will fail the whole run on any finding, since `ruff check .` has no `--exit-zero` - a change that reintroduces a bare `except Exception:` or similar fails CI, not just a local check. See the "Linting" section above for what's actually selected and why.

## Contribution Rules

These mirror [CONTRIBUTING.md](CONTRIBUTING.md); keep the two in step.

- A human reviews everything before it is submitted. Do not open pull requests, post issue comments, or reply in review threads on your own; prepare the change and let the person you are working for review and submit it.
- New features, new public API, new options, and behavior changes need an issue labeled `accepted` before a pull request is opened. If there is none, stop and tell the person you are working for.
- A contributor has at most 3 open pull requests. Check first: `gh pr list --author @me --state open`. Extra work stays in draft pull requests.
- One fix or feature per change. Do not mix refactors or formatting into unrelated work.
- Do not change version numbers or create tags unless the maintainer asks; releases are made by the maintainer.
- Run `ruff check .` and `pytest` before calling a change complete.
