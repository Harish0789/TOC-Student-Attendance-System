"""Small reusable widgets: cards, notification bar, tables, entries."""

import tkinter as tk
from tkinter import ttk

from .theme import C, FONT, MONO


class Card(tk.Frame):
    """White panel with an optional title and subtitle. Put content in .body."""

    def __init__(self, parent, title=None, subtitle=None, **kw):
        super().__init__(parent, bg=C["card"], highlightthickness=1,
                         highlightbackground=C["border"], **kw)
        if title:
            head = tk.Frame(self, bg=C["card"])
            head.pack(fill="x", padx=14, pady=(10, 2))
            tk.Label(head, text=title, bg=C["card"], fg=C["navy"],
                     font=(FONT, 12, "bold")).pack(side="left")
            self.head_right = tk.Frame(head, bg=C["card"])
            self.head_right.pack(side="right")
            if subtitle:
                tk.Label(self, text=subtitle, bg=C["card"], fg=C["muted"],
                         font=(FONT, 9), anchor="w", justify="left").pack(fill="x", padx=14)
        self.body = tk.Frame(self, bg=C["card"])
        self.body.pack(fill="both", expand=True, padx=14, pady=(6, 12))


class InfoBar(tk.Frame):
    """Coloured notification strip used for errors, warnings and recoveries."""

    KINDS = {
        "error": ("danger", "danger_bg", "✖"),
        "warning": ("warning", "warning_bg", "⚠"),
        "success": ("success", "success_bg", "✔"),
        "info": ("info", "info_bg", "ℹ"),
    }

    def __init__(self, holder):
        super().__init__(holder, bg=C["card"])
        self.stripe = tk.Frame(self, width=6)
        self.stripe.pack(side="left", fill="y")
        self.inner = tk.Frame(self)
        self.inner.pack(side="left", fill="both", expand=True)
        self.icon = tk.Label(self.inner, font=(FONT, 15, "bold"))
        self.icon.grid(row=0, column=0, rowspan=2, sticky="n", padx=(10, 8), pady=(8, 0))
        self.title = tk.Label(self.inner, font=(FONT, 11, "bold"), anchor="w", justify="left")
        self.title.grid(row=0, column=1, sticky="ew", pady=(9, 0))
        self.close = tk.Label(self.inner, text="✕", font=(FONT, 10), cursor="hand2")
        self.close.grid(row=0, column=2, sticky="ne", padx=8, pady=6)
        self.close.bind("<Button-1>", lambda e: self.hide())
        self.message = tk.Label(self.inner, font=(FONT, 10), anchor="w", justify="left")
        self.message.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(2, 4), padx=(0, 10))
        self.details = tk.Label(self.inner, font=(MONO, 9), anchor="w", justify="left",
                                bg="#ffffff", padx=8, pady=5)
        self.actions = tk.Frame(self.inner)
        self.inner.columnconfigure(1, weight=1)
        self.bind("<Configure>", self._rewrap)
        self.visible = False
        self.kind = None

    def _rewrap(self, _event=None):
        width = max(200, self.winfo_width() - 80)
        self.message.configure(wraplength=width)
        self.details.configure(wraplength=width)
        self.title.configure(wraplength=width - 30)

    def show(self, kind, title, message="", details=None, actions=()):
        fg_key, bg_key, icon = self.KINDS[kind]
        fg, bg = C[fg_key], C[bg_key]
        self.kind = kind
        self.configure(bg=bg, highlightthickness=1, highlightbackground=fg)
        self.stripe.configure(bg=fg)
        for w in (self.inner, self.actions):
            w.configure(bg=bg)
        self.icon.configure(text=icon, bg=bg, fg=fg)
        self.title.configure(text=title, bg=bg, fg=fg)
        self.close.configure(bg=bg, fg=fg)
        self.message.configure(text=message, bg=bg, fg=C["text"])
        if details:
            self.details.configure(text=details, fg=C["text"])
            self.details.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(0, 10), pady=(0, 6))
        else:
            self.details.grid_remove()
        for child in self.actions.winfo_children():
            child.destroy()
        if actions:
            for i, (label, callback) in enumerate(actions):
                ttk.Button(self.actions, text=label, command=callback,
                           style="Primary.TButton" if i == 0 else "Ghost.TButton"
                           ).pack(side="left", padx=(0, 8))
            self.actions.grid(row=3, column=1, columnspan=2, sticky="w", pady=(0, 9))
        else:
            self.actions.grid_remove()
        if not self.visible:
            self.pack(fill="x")
            self.visible = True
        self._rewrap()

    def hide(self):
        if self.visible:
            self.pack_forget()
            self.master.configure(height=1)  # an empty Tk frame keeps its old size otherwise
            self.visible = False


def info_bar(parent):
    """A holder frame that collapses to zero height when its InfoBar is hidden."""
    holder = tk.Frame(parent, bg=parent.cget("bg"))
    return holder, InfoBar(holder)


def make_tree(parent, columns, height=10, style="Treeview"):
    """columns: list of (id, heading, width, anchor). Returns (frame, tree)."""
    frame = tk.Frame(parent, bg=C["card"], highlightthickness=1, highlightbackground=C["border"])
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings",
                        height=height, selectmode="extended", style=style)
    k = max(1.0, parent.winfo_fpixels("1i") / 96.0)  # column widths are pixels: scale for DPI
    for cid, heading, width, anchor in columns:
        tree.heading(cid, text=heading, anchor=anchor)
        tree.column(cid, width=int(width * k), minwidth=40, anchor=anchor, stretch=True)
    bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    return frame, tree


def entry(parent, width=22, mono=False, size=11):
    return tk.Entry(parent, width=width, font=(MONO if mono else FONT, size), relief="flat",
                    bg="#ffffff", fg=C["text"], insertbackground=C["text"],
                    highlightthickness=2, highlightbackground=C["border"],
                    highlightcolor=C["primary"])


def set_entry_state(widget, kind):
    """Colour an entry border: None / 'ok' / 'live' / 'error'."""
    color = {"ok": "#16a34a", "live": "#d97706", "error": "#dc2626"}.get(kind)
    widget.configure(highlightbackground=color or C["border"],
                     highlightcolor=color or C["primary"])


def label(parent, text="", size=10, bold=False, color=None, mono=False, **kw):
    return tk.Label(parent, text=text, bg=kw.pop("bg", parent.cget("bg")),
                    fg=color or C["text"],
                    font=(MONO if mono else FONT, size, "bold" if bold else "normal"), **kw)


class Badge(tk.Label):
    def __init__(self, parent, text, bg, fg):
        super().__init__(parent, text=text, bg=bg, fg=fg, font=(FONT, 10, "bold"),
                         padx=10, pady=4)
