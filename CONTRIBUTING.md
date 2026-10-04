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
    terminal_overlay.py   # TerminalOverlay: setup, lifecycle, entry-field state machine
    overlay_ui.py          # Widget construction, help panel, tooltips, confirm popup
    overlay_positioning.py # Terminal tracking, following, and the lock
    overlay_tabs.py         # Tab create/rename/switch/delete
    overlay_todos.py        # Todo add/edit/toggle/remove/reorder/undo
    overlay_theme.py        # Colors, sizing constants, HELP_ROWS
    winutil.py            # Terminal detection, DPI, Win32 event hooks
    storage.py            # Load / migrate / atomically save todos
    lockfile.py           # PID-based single-instance lock
  tests/                  # pytest suite
  .github/workflows/      # ci.yml (lint + test on PRs), release.yml (publish on a version tag)
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

**Automated** - `ruff check .` and `pytest` (both green; add tests for your change, and see AGENTS.md's "Linting" section before narrowing or suppressing a finding). `tests/test_overlay_smoke.py` instantiates the real overlay headlessly and covers most tab/todo behavior directly - extend it rather than only adding manual checks below.

**Manual** - fills in what automated coverage doesn't reach (real mouse/keyboard timing, visual layout):

- ✅ `sidenote` starts the overlay, `sidenote status` reports it
- ✅ `sidenote stop` stops it - and leaves your other Python processes alone
- ✅ `sidenote init` adds working PowerShell functions
- ✅ Overlay sits flush against the terminal, matching its height
- ✅ `Shift+Tab` toggles visibility
- ✅ Double-click checks a todo off; `Ctrl+Delete` clears completed ones
- ✅ `Enter` on a todo edits it in place; `Escape` cancels without saving
- ✅ Right-click copies a todo, including one that's selected; the list scrolls by wheel and arrow keys
- ✅ Dragging a todo reorders it, and `Ctrl+Z` restores a todo (or a `Ctrl+Delete` batch) you just deleted
- ✅ `+` adds a tab (up to 5); double-clicking its name in the footer renames it
- ✅ The footer `×` deletes the current tab after confirming, and doesn't show with only one tab left
- ✅ A width set by dragging the edge survives the terminal being moved or resized
- ✅ `Ctrl+`/`Ctrl-` resizes the text and clamps at both ends
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
6. Open a PR with a clear description and fill in the template. CI (`ruff check .` and `pytest` on Python 3.9 and 3.13) must pass before it can be merged.

### Proposing Features

New features, new options, and changes to default behavior start as an issue. Describe the problem and the approach you have in mind, then wait for the maintainer to label it `accepted` before opening a PR, and link that issue from the PR. Bug fixes, test fixes, and documentation corrections can go straight to a PR.

### Open Pull Request Limit

Please keep at most 3 PRs open at a time. Once 3 are open, keep further work on a branch or in a draft PR until one is merged or closed. Drafts don't count and aren't reviewed until marked ready. There is one maintainer, and this keeps every PR getting a careful review. It's a written policy, not an automated check.

### AI-Assisted Contributions

AI coding tools are welcome for writing code and drafting reviews. You are responsible for everything you submit: review the code and the PR description yourself and submit it yourself, and confirm that in the PR or issue template. Automated bot-to-bot conversation on issues and PRs isn't allowed. Coding agents working in this repo should read [AGENTS.md](AGENTS.md), which carries the same rules.

### Labels and Release Notes

Release notes are generated from PR labels (`.github/release.yml`). The maintainer labels PRs at merge time: `bug`, `enhancement`, `documentation`, `performance`, `security`, `breaking`, `ci`, `chore`, or `dependencies`. `skip-changelog` leaves a PR out of the notes.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Publishing (Maintainers Only)

Merging to `master` does not publish. A release happens when a version tag is pushed, and `.github/workflows/release.yml` does the rest: it checks the tag against the version in `pyproject.toml` and `sidenote/__init__.py`, builds the wheel and sdist, attests build provenance, creates a draft GitHub Release with generated notes, publishes to PyPI through trusted publishing (no stored token), publishes the release, and confirms PyPI serves the new version.

To release:

```powershell
# 1. In a PR: bump the version in pyproject.toml AND sidenote/__init__.py,
#    move the CHANGELOG.md [Unreleased] notes under the new version. Merge it.
git checkout master; git pull
ruff check .; pytest              # both green

# 2. Tag the merged commit and push only the tag
git tag -a v1.5.0 -m "Release v1.5.0"
git push origin v1.5.0
```

A release candidate works the same way with a tag like `v1.5.0-rc.1`; the manifests then say `1.5.0rc1` (PEP 440), and the GitHub Release is marked as a pre-release. Registries never accept a version number twice, so if a release goes wrong, fix forward with the next patch version.

Publishing needs the trusted publisher configured once on PyPI (owner `Lyellr88`, repository `sidenote`, workflow `release.yml`, environment `pypi`). There is no `PYPI_API_TOKEN` any more. If trusted publishing is unavailable, a manual upload (`python -m build`, `twine check dist/*`, `twine upload dist/*`) needs a new PyPI API token created for that purpose; the old repository token is revoked and the CI no longer reads it.

## Questions or Ideas

Open an issue or discussion on GitHub. This tool exists because context-switching kills ADHD focus - if you have ideas to make it better at that, let's talk.

## What We're NOT Looking For

- Heavy frameworks or dependencies
- Features that add complexity
- Anything that slows down the 3-second capture window
- Multi-platform rewrites that break Windows support

Keep it lightweight, keep it fast, keep it focused.
