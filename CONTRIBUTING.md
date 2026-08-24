# Contributing to Sidenote

Thanks for considering contributing! This is a small personal-use tool built for ADHD developers, but PRs are welcome.

## Quick Start

```powershell
git clone https://github.com/lyellr88/sidenote.git
cd sidenote

# Install in editable mode, with test dependencies
pip install -e ".[dev]"

# Run the tests
pytest

# Test it for real
sidenote
```

## Project Structure

```
sidenote/
  sidenote/
    __init__.py           # Package metadata
    __main__.py           # Enables `pythonw -m sidenote`
    cli.py                # Command entry point (start/stop/status/upgrade/init)
    _upgrade.py           # Detached helper for `sidenote upgrade`
    terminal_overlay.py   # tkinter UI, positioning, event handling
    winutil.py            # Terminal detection, DPI, Win32 event hooks
    storage.py            # Load / migrate / atomically save todos
    lockfile.py           # PID-based single-instance lock
  tests/                  # pytest suite
  pyproject.toml          # Package config
  README.md               # User guide
  DOCS.md                 # FAQ, troubleshooting, internals
  AGENTS.md               # Architecture notes and invariants
  setup.ps1               # Setup for cloned repos
```

`AGENTS.md` documents the invariants that are easy to break by accident - threading rules, why detection is process-based, and why nothing may be killed by image name. Worth reading before a non-trivial change.

## Making Changes

**For bug fixes:**
1. Write a failing test that reproduces it
2. Make the minimal fix
3. Confirm the test passes and `pytest` is green
4. Update README if user-facing

**For new features:**
1. Open an issue first to discuss
2. Keep it simple - this tool is meant to be lightweight
3. Match the existing code style
4. Add tests for anything that isn't pure UI
5. Test manually with `pip install -e .`

## Testing Checklist

Before submitting a PR:

**Automated** - `pytest` (all green; add tests for your change)

**Manual** - the tkinter UI isn't covered automatically:

- ✅ `sidenote` starts the overlay, `sidenote status` reports it
- ✅ `sidenote stop` stops it - and leaves your other Python processes alone
- ✅ `sidenote init` adds working PowerShell functions
- ✅ Overlay sits flush against the terminal, matching its height
- ✅ `Shift+Tab` toggles visibility
- ✅ Double-click checks a todo off; `Ctrl+Delete` clears completed ones
- ✅ Right-click copies a todo, including one that's selected; the list scrolls by wheel and arrow keys
- ✅ Dragging a todo reorders it, and `Ctrl+Z` restores a todo (or a `Ctrl+Delete` batch) you just deleted
- ✅ `+` adds a tab (up to 5); double-clicking its name in the footer renames it
- ✅ A width set by dragging the edge survives the terminal being moved or resized
- ✅ `?` panel lists the actions and closes again
- ✅ Todos persist after closing/reopening
- ✅ Lock button (🔓/🔒) works
- ✅ Overlay follows terminal movement, snapping, and maximising
- ✅ Commands work from any directory

## Code Style

- Keep it simple - no unnecessary abstractions
- Match existing patterns
- Comments only for non-obvious "why"
- Windows-only for now (PRs for Linux/Mac welcome but keep them separate)

## Submitting Changes

1. Fork the repo
2. Create a branch: `fix/terminal-detection` or `feature/dark-mode`
3. Make focused changes (one fix/feature per PR)
4. Test manually
5. Update README for user-facing changes
6. Open a PR with a clear description

## Publishing (Maintainers Only)

```powershell
# Bump version in pyproject.toml and sidenote/__init__.py
pytest              # must be green before publishing

# Clear dist/ first. Bumping the version does not rebuild, so a leftover
# artifact gets uploaded instead - or collides with its published twin and
# fails the whole command.
Remove-Item -Recurse -Force dist, build, *.egg-info -ErrorAction SilentlyContinue
python -m build
twine check dist/*
twine upload dist/*
```

## Questions or Ideas

Open an issue or discussion on GitHub. This tool exists because context-switching kills ADHD focus - if you have ideas to make it better at that, let's talk.

## What We're NOT Looking For

- Heavy frameworks or dependencies
- Features that add complexity
- Anything that slows down the 3-second capture window
- Multi-platform rewrites that break Windows support

Keep it lightweight, keep it fast, keep it focused.
