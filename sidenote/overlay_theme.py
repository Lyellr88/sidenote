"""Colors, sizing constants, and the help panel's action list.

Pure data, no behavior - shared across the overlay's UI, positioning, tabs,
and todos modules, which is why it lives on its own rather than inside any
one of them.
"""

BG = "#1e1e1e"
BAR_BG = "#2d2d30"
LIST_BG = "#252526"
SELECT_BG = "#2f3033"
FG = "#cccccc"
MUTED = "#858585"
DONE_FG = "#6a6a6a"
ERROR_FG = "#f48771"
LOCKED_BG = "#8b0000"
ACCENT = "#60a5fa"

BASE_WIDTH = 280
PUMP_MS = 40
FALLBACK_POLL_MS = 2000
REPOSITION_DEBOUNCE_MS = 60

COPY_FLASH = ["#4ec9b0", "#3f9c88", "#317a6c"]
COPY_FLASH_MS = 70

HELP_ROWS = [
    ("Shift+Tab", "Toggle overlay (works anywhere)"),
    ("Enter", "Add todo"),
    ("Double-click", "Check off / uncheck a todo"),
    ("Right-click", "Copy a todo's text"),
    ("Enter on a todo", "Edit its text"),
    ("Drag a todo", "Reorder it in the list"),
    ("Space", "Check off / uncheck selection"),
    ("Delete", "Remove selected todo"),
    ("Ctrl+Delete", "Clear all checked-off todos"),
    ("Ctrl+Z", "Undo the last delete"),
    ("+ button", "Add a tab (up to 5)"),
    ("Double-click tab name", "Rename the current tab"),
    ("× next to tab name", "Delete the current tab, with confirmation"),
    ("Escape", "Hide overlay"),
    ("Lock button", "Stick to one specific terminal"),
    ("Drag title bar", "Detach and place it yourself"),
]
