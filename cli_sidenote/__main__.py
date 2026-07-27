"""Allow ``pythonw -m cli_sidenote`` to launch the overlay directly."""

import sys

from .terminal_overlay import main

if __name__ == "__main__":
    sys.exit(main())
