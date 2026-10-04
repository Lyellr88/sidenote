# Security Policy

## Supported Versions

Security fixes are released for the latest minor version only. Please upgrade (`sidenote upgrade`) before reporting.

| Version | Supported |
|---|---|
| 1.4.x | Yes |
| Older | No |

## Reporting a Vulnerability

Please do not report security vulnerabilities through public issues, discussions, or pull requests.

Report privately through GitHub: open the repository's Security tab and choose "Report a vulnerability", or go directly to <https://github.com/Lyellr88/sidenote/security/advisories/new>.

Or email the maintainer:

**lyellr88@gmail.com**

Include:

- A short summary of the issue
- Affected version or commit
- Reproduction steps
- Impact assessment
- Suggested fix, if known

You can expect an acknowledgment within 7 days, and credit in the release notes unless you prefer to stay anonymous. Please give a reasonable amount of time to release a fix before any public disclosure.

## Scope

Security-sensitive areas include:

- Global hotkey registration (keyboard library)
- Windows API calls and window manipulation
- Local data storage (`~/.terminal_todos.json`)
- Process spawning and management
- PyPI package distribution

## Known Limitations

- **Local only**: Sidenote itself makes no network requests. The one exception is `sidenote upgrade`, which runs `pip` against PyPI at your request.
- **Single user**: Designed for personal use on your own machine
- **Windows API**: Uses Windows API for window detection and positioning
- **File permissions**: Todo data stored in user home directory with default permissions
- **Process management**: Uses `taskkill` to stop the overlay process

## Public Disclosure

This is a small personal-use tool. If you find a security issue, please report it so we can fix it for everyone.
