# Security Policy

## Reporting a Vulnerability

Please report security issues by opening a GitHub issue or emailing the maintainer.

**lyellr88@gmail.com**

Include:

- A short summary of the issue
- Affected version or commit
- Reproduction steps
- Impact assessment
- Suggested fix, if known

## Scope

Security-sensitive areas include:

- Global hotkey registration (keyboard library)
- Windows API calls and window manipulation
- Local data storage (`~/.terminal_todos.json`)
- Process spawning and management
- PyPI package distribution

## Known Limitations

- **Local only**: This tool runs locally and does not make network requests
- **Single user**: Designed for personal use on your own machine
- **Windows API**: Uses Windows API for window detection and positioning
- **File permissions**: Todo data stored in user home directory with default permissions
- **Process management**: Uses `taskkill` to stop the overlay process

## Public Disclosure

This is a small personal-use tool. If you find a security issue, please report it so we can fix it for everyone.
