"""Overlay chrome: widget construction, the help panel, tooltips, and the
generic confirmation popup. No tab or todo business logic - callers like
TabsMixin decide *when* to show a confirm dialog and what it says; this owns
*how* it's drawn.
"""

import tkinter as tk

from .overlay_theme import (
    BAR_BG,
    BASE_WIDTH,
    BG,
    ERROR_FG,
    FG,
    HELP_ROWS,
    LIST_BG,
    MUTED,
    SELECT_BG,
)


class OverlayUIMixin:
    def setup_window(self):
        self.root.title("")
        self.root.geometry(f"{BASE_WIDTH}x600+100+100")
        self.root.configure(bg=BG)
        self.root.withdraw()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.bind("<Configure>", self._on_configure)

    def setup_ui(self):
        drag_bar = tk.Frame(self.root, bg=BAR_BG, height=25, cursor="fleur")
        drag_bar.pack(fill=tk.X)
        drag_bar.pack_propagate(False)

        self.add_tab_btn = tk.Label(
            drag_bar,
            text="+",
            bg=BAR_BG,
            fg=FG,
            cursor="hand2",
            font=("Consolas", 10, "bold"),
            padx=6,
        )
        self.add_tab_btn.pack(side=tk.LEFT)
        self.add_tab_btn.bind("<Button-1>", lambda e: self.start_new_tab())

        # Populated by _render_tabs() once a second tab exists.
        self.tabs_frame = tk.Frame(drag_bar, bg=BAR_BG)
        self.tabs_frame.pack(side=tk.LEFT)

        # Packed right-to-left: lock lands at the far edge, help lands just
        # left of it.
        self.lock_btn = tk.Label(
            drag_bar,
            text="\U0001f513",
            bg=BAR_BG,
            fg="white",
            cursor="hand2",
            font=("Segoe UI", 11),
            padx=5,
            pady=2,
        )
        self.lock_btn.pack(side=tk.RIGHT, padx=2)
        self.lock_btn.bind("<Button-1>", lambda e: self.toggle_lock())
        self.lock_btn.bind("<Enter>", self.show_lock_tooltip)
        self.lock_btn.bind("<Leave>", self.hide_lock_tooltip)

        self.help_btn = tk.Label(
            drag_bar,
            text="?",
            bg=BAR_BG,
            fg=FG,
            cursor="hand2",
            font=("Consolas", 10, "bold"),
            padx=6,
        )
        self.help_btn.pack(side=tk.RIGHT)
        self.help_btn.bind("<Button-1>", lambda e: self.toggle_help())

        # place(), not pack(): the buttons on either side are different widths,
        # so packing the title into what's left between them centres it off-centre.
        title = tk.Label(
            drag_bar,
            text="Sidenote",
            fg=FG,
            bg=BAR_BG,
            font=("Consolas", 9),
            cursor="fleur",
        )
        title.place(relx=0.5, rely=0.5, anchor="center")

        for widget in (drag_bar, title):
            widget.bind("<Button-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.on_drag)

        input_frame = tk.Frame(self.root, bg=BG)
        input_frame.pack(fill=tk.X, padx=8, pady=8)

        self.entry = tk.Entry(
            input_frame,
            bg="#3e3e42",
            fg="white",
            insertbackground="white",
            relief="flat",
            font=("Consolas", 10),
            bd=5,
            highlightthickness=0,
        )
        self.entry.pack(fill=tk.X)
        self.entry.bind("<Return>", self._on_entry_return)
        self.entry.bind("<Escape>", self._on_entry_escape)

        list_container = tk.Frame(self.root, bg=BG)
        list_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=0)

        # No scrollbar: the list still scrolls by wheel, and by arrow keys once
        # a row is selected.
        self.listbox = tk.Listbox(
            list_container,
            bg=LIST_BG,
            fg=FG,
            selectbackground=SELECT_BG,
            # Empty means "keep the row's own colour", so selecting a done todo
            # doesn't wash out its grey, and the copy flash still shows.
            selectforeground="",
            relief="flat",
            font=("Consolas", 9),
            bd=0,
            # Default is a 1px SystemButtonFace ring, which reads as a white
            # border whenever the list doesn't have focus.
            highlightthickness=0,
            activestyle="none",
        )
        self.listbox.pack(fill=tk.BOTH, expand=True)

        self.listbox.bind("<MouseWheel>", self._on_mousewheel)
        self.listbox.bind("<Button-3>", self.copy_todo)
        self.listbox.bind("<Double-Button-1>", self.toggle_done)
        self.listbox.bind("<space>", self.toggle_done)
        self.listbox.bind("<Delete>", self.remove_todo)
        self.listbox.bind("<BackSpace>", self.remove_todo)
        self.listbox.bind("<Control-Delete>", self.clear_done)
        self.listbox.bind("<Return>", self.start_edit_todo)
        self.listbox.bind("<KP_Enter>", self.start_edit_todo)
        self.listbox.bind("<Escape>", lambda e: self.hide())

        # Drag-to-reorder: press records the row, motion moves it live, release
        # persists it. These run alongside (not instead of) the Listbox's own
        # click-to-select and double-click-to-toggle handling.
        self.listbox.bind("<Button-1>", self._on_list_press)
        self.listbox.bind("<B1-Motion>", self._on_list_drag)
        self.listbox.bind("<ButtonRelease-1>", self._on_list_release)

        self.root.bind_all("<Control-z>", self.undo)

        # "+" is Shift+= on most keyboards, so Tk reports it as either
        # keysym depending on layout - bind both, plus the numpad keys.
        for sequence in ("<Control-plus>", "<Control-equal>", "<Control-KP_Add>"):
            self.root.bind_all(sequence, self.increase_font_size)
        for sequence in ("<Control-minus>", "<Control-KP_Subtract>"):
            self.root.bind_all(sequence, self.decrease_font_size)

        footer = tk.Frame(self.root, bg=BAR_BG, height=30)
        footer.pack(fill=tk.X)
        footer.pack_propagate(False)

        self.tab_label = tk.Label(
            footer,
            text="",
            fg=MUTED,
            bg=BAR_BG,
            font=("Consolas", 8),
            anchor="w",
            cursor="hand2",
            padx=8,
        )
        self.tab_label.pack(side=tk.LEFT, fill=tk.Y)
        self.tab_label.bind("<Double-Button-1>", lambda e: self.start_rename_tab())

        # Only packed once a second tab exists - see _update_tab_label(). You
        # can't delete the one tab that's left.
        self.delete_tab_btn = tk.Label(
            footer, text="×", fg=MUTED, bg=BAR_BG, cursor="hand2", font=("Consolas", 10)
        )
        self.delete_tab_btn.bind("<Button-1>", lambda e: self._confirm_delete_tab())

        self.status = tk.Label(
            footer,
            text="",
            fg=MUTED,
            bg=BAR_BG,
            font=("Consolas", 8),
            anchor="e",
            padx=8,
        )
        self.status.pack(side=tk.RIGHT, fill=tk.Y)

        self.drag_start_x = 0
        self.drag_start_y = 0

    # -------------------------------------------------------------- dragging

    def start_drag(self, event):
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.follow_terminal = False  # manual placement wins over auto-follow
        self.set_status("Detached - lock to re-attach")

    def on_drag(self, event):
        x = self.root.winfo_x() + (event.x - self.drag_start_x)
        y = self.root.winfo_y() + (event.y - self.drag_start_y)
        self.root.geometry(f"+{x}+{y}")

    # --------------------------------------------------------------- tooltips

    def show_lock_tooltip(self, event):
        text = (
            "Locked to terminal" if self.is_locked else "Click to lock to this terminal"
        )
        self.hide_lock_tooltip()
        self._lock_tooltip = tk.Toplevel(self.root)
        self._lock_tooltip.wm_overrideredirect(True)
        self._lock_tooltip.wm_geometry(f"+{event.x_root + 10}+{event.y_root + 10}")
        tk.Label(
            self._lock_tooltip,
            text=text,
            bg=BG,
            fg="white",
            relief="solid",
            borderwidth=1,
            font=("Consolas", 8),
            padx=5,
            pady=2,
        ).pack()

    def hide_lock_tooltip(self, event=None):
        if self._lock_tooltip:
            self._lock_tooltip.destroy()
            self._lock_tooltip = None

    # ------------------------------------------------------------- help panel

    def toggle_help(self):
        if self._help_window:
            self.hide_help()
        else:
            self.show_help()

    def show_help(self):
        self.hide_help()
        panel = tk.Toplevel(self.root)
        panel.wm_overrideredirect(True)
        panel.configure(bg=BG, highlightbackground="#3e3e42", highlightthickness=1)

        header = tk.Frame(panel, bg=BAR_BG)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="Quick actions",
            bg=BAR_BG,
            fg=FG,
            font=("Consolas", 9, "bold"),
            padx=8,
            pady=4,
        ).pack(side=tk.LEFT)
        close = tk.Label(
            header,
            text="×",
            bg=BAR_BG,
            fg=MUTED,
            font=("Consolas", 11),
            cursor="hand2",
            padx=8,
        )
        close.pack(side=tk.RIGHT)
        close.bind("<Button-1>", lambda e: self.hide_help())

        body = tk.Frame(panel, bg=BG)
        body.pack(fill=tk.BOTH, padx=10, pady=8)
        for row, (keys, description) in enumerate(HELP_ROWS):
            tk.Label(
                body,
                text=keys,
                bg=BG,
                fg="#9cdcfe",
                font=("Consolas", 8, "bold"),
                anchor="w",
            ).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=1)
            tk.Label(
                body, text=description, bg=BG, fg=FG, font=("Consolas", 8), anchor="w"
            ).grid(row=row, column=1, sticky="w", pady=1)

        panel.update_idletasks()
        x = self.help_btn.winfo_rootx()
        y = self.help_btn.winfo_rooty() + self.help_btn.winfo_height() + 2
        # Keep the panel on screen when the overlay sits near a screen edge.
        max_x = self.root.winfo_screenwidth() - panel.winfo_reqwidth() - 4
        panel.wm_geometry(f"+{max(4, min(x, max_x))}+{y}")

        self._help_window = panel

    def hide_help(self):
        if self._help_window:
            self._help_window.destroy()
            self._help_window = None

    # --------------------------------------------------------- confirm popup

    def _show_confirm(self, message, on_confirm, anchor_widget):
        """Small themed confirmation popup, sized to fit next to the overlay
        rather than a native OS dialog."""
        self._hide_confirm()
        panel = tk.Toplevel(self.root)
        panel.wm_overrideredirect(True)
        panel.configure(bg=BG, highlightbackground="#3e3e42", highlightthickness=1)

        tk.Label(
            panel,
            text=message,
            bg=BG,
            fg=FG,
            font=("Consolas", 8),
            wraplength=200,
            justify="left",
            padx=10,
            pady=8,
        ).pack(fill=tk.X)

        buttons = tk.Frame(panel, bg=BG)
        buttons.pack(fill=tk.X, padx=10, pady=(0, 8))

        def confirm(event=None):
            self._hide_confirm()
            on_confirm()

        delete_btn = tk.Label(
            buttons,
            text="Delete",
            bg=ERROR_FG,
            fg=BG,
            cursor="hand2",
            font=("Consolas", 8, "bold"),
            padx=8,
            pady=3,
        )
        delete_btn.pack(side=tk.RIGHT)
        delete_btn.bind("<Button-1>", confirm)

        cancel_btn = tk.Label(
            buttons,
            text="Cancel",
            bg="#3e3e42",
            fg=FG,
            cursor="hand2",
            font=("Consolas", 8),
            padx=8,
            pady=3,
        )
        cancel_btn.pack(side=tk.RIGHT, padx=(0, 6))
        cancel_btn.bind("<Button-1>", lambda e: self._hide_confirm())

        panel.update_idletasks()
        x = anchor_widget.winfo_rootx()
        y = anchor_widget.winfo_rooty() - panel.winfo_reqheight() - 4
        max_x = self.root.winfo_screenwidth() - panel.winfo_reqwidth() - 4
        panel.wm_geometry(f"+{max(4, min(x, max_x))}+{max(4, y)}")

        panel.bind("<Escape>", lambda e: self._hide_confirm())
        panel.bind("<Delete>", confirm)
        panel.focus_set()
        self._confirm_window = panel

    def _hide_confirm(self):
        if self._confirm_window:
            self._confirm_window.destroy()
            self._confirm_window = None
