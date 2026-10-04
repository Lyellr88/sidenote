# Changelog

All notable changes to Sidenote are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/). Full release notes are on the [Releases page](https://github.com/Lyellr88/sidenote/releases).

## [Unreleased]

### Changed

- Python 3.9 is now the minimum supported version (`requires-python = ">=3.9"`). The 3.7 and 3.8 classifiers are gone.
- CI runs on every pull request and every push to `master` (ruff on Python 3.13, pytest on 3.9 and 3.13), with dependency caching, job timeouts, cancellation of superseded runs, and workflow linting with actionlint. A single `ci-ok` job summarizes the result for branch protection.
- Publishing moved out of CI. Pushing a version tag (`vX.Y.Z`) now runs `release.yml`, which checks the tag against both `pyproject.toml` and `sidenote/__init__.py`, builds and smoke-tests the package, attests build provenance, publishes to PyPI through trusted publishing (no stored token), and publishes the GitHub Release. Pre-release tags such as `v1.5.0-rc.1` are supported.
- GitHub Actions are pinned to commit SHAs, and workflows run with read-only token permissions unless a job needs more.
- `SECURITY.md` points to private vulnerability reporting, lists supported versions, and no longer claims the tool never touches the network (`sidenote upgrade` runs pip).

### Added

- Dependabot updates for pip and GitHub Actions.
- Pull request template, bug and feature issue templates, and `.github/release.yml`, which groups release notes by label.
- Written contribution rules (accepted-issue flow for features, three open pull requests per contributor, AI-assisted contribution policy) in `CONTRIBUTING.md` and `AGENTS.md`.
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1) and this changelog.

### Fixed

- README links to `DOCS.md` and `CONTRIBUTING.md` pointed at the `main` branch, which does not exist, and returned 404 on GitHub and PyPI.

## [1.4.0] - 2026-08-24

### Added

- Text zoom: `Ctrl+` (or `Ctrl+=`) grows the list and entry text, `Ctrl-` shrinks it, one point at a time between 7pt and 20pt. It works from the entry field or the list and resets on restart.

## [1.3.2] - 2026-08-24

### Changed

- Added a scoped ruff configuration to `pyproject.toml` and fixed every finding under it: broad `except Exception` clauses were narrowed where a real exception type exists and documented where they deliberately catch arbitrary callback errors. CI runs `ruff check .` before the tests.

## [1.3.1] - 2026-08-24

### Changed

- Internal refactor: `terminal_overlay.py` was split into `overlay_ui.py`, `overlay_positioning.py`, `overlay_tabs.py`, `overlay_todos.py`, and `overlay_theme.py`. Methods moved verbatim into mixin classes; no behavior changed. First release published by the CI pipeline.

## [1.3.0] - 2026-08-24

### Added

- Edit a todo in place: select it, press `Enter`, change the text, and press `Enter` to save or `Escape` to cancel.
- Headless tests for the tkinter overlay (`tests/test_overlay_smoke.py`) covering tabs, drag-reorder, undo, editing, and the header-overlap regression.
- A GitHub Actions workflow that ran the test suite and published to PyPI on every push to `master`.

## [1.2.2] - 2026-08-24

### Fixed

- `sidenote upgrade` could report success without installing anything because pip trusted a stale local cache. It now runs with `--no-cache-dir`, as do the manual commands it prints on failure.

### Changed

- In the tab-delete confirmation popup, the `Delete` key now confirms, matching the Delete button. `Escape` still cancels.

## [1.2.1] - 2026-08-24

### Added

- Tab deletion: a `×` next to the tab name in the footer opens a confirmation popup naming the tab and its todo count. The last remaining tab cannot be deleted.

## [1.2.0] - 2026-08-24

### Added

- Tabs: up to 5 separate lists, added with `+`, switched with the numbered buttons, renamed by double-clicking the name in the footer. Existing todos become the first tab automatically.
- Drag a todo to reorder it.
- `Ctrl+Z` undoes the last delete, whether a single todo or a `Ctrl+Delete` batch.

### Changed

- The header and footer layout: `+` takes the top-left spot, `?` sits next to the lock button, and the footer shows the current tab name and the open/done count.
- The todos file gains a tabs structure the first time it loads. Older versions cannot read it, so back up `~/.terminal_todos.json` before downgrading.

## [1.1.2] - 2026-07-31

### Added

- Right-click a todo to copy its text, with a colour fade to confirm.
- Drag the overlay's edge to widen it. The width is kept until restart instead of snapping back.

### Changed

- Quieter interface: centred name in the header, empty window title, no scrollbar, no white focus border, and a subtler selection colour.

### Fixed

- The copy fade did not show on an already-selected row, and completed todos lost their grey while selected.
- The PATH repair snippet in `DOCS.md` ran three statements on one line, so it silently did nothing.
- The FAQ wrongly said the overlay could not be resized.

## [1.0.0] - 2026-07-27

### Added

- First release: a todo overlay docked to the terminal window, following it and syncing z-order, with a `Shift+Tab` global hotkey, check-off and `Ctrl+Delete` clear, a lock button, a built-in help panel, atomic persistent storage, event-driven window tracking, and a dark theme.
- Commands: `sidenote`, `sidenote stop`, `sidenote status`, `sidenote version`, and `sidenote upgrade`.
- Thread-safe UI updates, PID-based process termination, process-based terminal detection, stale lock recovery, DPI awareness, and tests for storage, the lockfile, terminal detection, and the CLI.

[Unreleased]: https://github.com/Lyellr88/sidenote/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/Lyellr88/sidenote/compare/v1.3.2...v1.4.0
[1.3.2]: https://github.com/Lyellr88/sidenote/compare/v1.3.1...v1.3.2
[1.3.1]: https://github.com/Lyellr88/sidenote/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/Lyellr88/sidenote/compare/v1.2.2...v1.3.0
[1.2.2]: https://github.com/Lyellr88/sidenote/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/Lyellr88/sidenote/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/Lyellr88/sidenote/compare/v1.1.2...v1.2.0
[1.1.2]: https://github.com/Lyellr88/sidenote/compare/v1.0.0...v1.1.2
[1.0.0]: https://github.com/Lyellr88/sidenote/releases/tag/v1.0.0
