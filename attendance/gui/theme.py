"""Colours, fonts and ttk styles shared by every screen."""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ..fsm import ABSENT, EXCUSED, LATE, NOT_MARKED, ON_DUTY, PRESENT

FONT = "Segoe UI"
MONO = "Consolas"

C = {
    "bg": "#eef2f7",
    "card": "#ffffff",
    "border": "#d5dce6",
    "text": "#0f172a",
    "muted": "#5b6b80",
    "navy": "#1e3a8a",
    "navy_dark": "#172e6e",
    "primary": "#2563eb",
    "primary_dark": "#1d4ed8",
    "success": "#15803d",
    "success_bg": "#dcfce7",
    "warning": "#b45309",
    "warning_bg": "#fef3c7",
    "danger": "#b91c1c",
    "danger_bg": "#fee2e2",
    "info": "#0369a1",
    "info_bg": "#e0f2fe",
    "soft": "#f1f5f9",
    "highlight": "#facc15",
}

# state -> (background, foreground, label)
STATE_STYLE = {
    NOT_MARKED: ("#f1f5f9", "#475569", "Not marked"),
    PRESENT: ("#dcfce7", "#166534", "Present"),
    LATE: ("#fef3c7", "#92400e", "Late"),
    ABSENT: ("#fee2e2", "#991b1b", "Absent"),
    EXCUSED: ("#ede9fe", "#5b21b6", "Excused"),
    ON_DUTY: ("#cffafe", "#155e75", "On duty"),
}


def setup_styles(root: tk.Tk) -> ttk.Style:
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name).configure(family=FONT, size=10)
        except tk.TclError:
            pass
    root.configure(bg=C["bg"])
    style = ttk.Style(root)
    style.theme_use("clam")
    line = tkfont.Font(family=FONT, size=10).metrics("linespace")

    style.configure(".", background=C["bg"], foreground=C["text"], font=(FONT, 10),
                    bordercolor=C["border"])
    style.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(12, 8, 12, 0))
    style.configure("TNotebook.Tab", padding=(16, 7), font=(FONT, 10, "bold"),
                    background="#dfe6f0", foreground=C["muted"], borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", C["card"])],
              foreground=[("selected", C["navy"])])

    def button(name, bg, active, fg="#ffffff"):
        style.configure(name, background=bg, foreground=fg, borderwidth=0, focusthickness=0,
                        padding=(14, 6), font=(FONT, 10, "bold"))
        style.map(name, background=[("disabled", "#cbd5e1"), ("active", active)],
                  foreground=[("disabled", "#f8fafc")])

    button("Primary.TButton", C["primary"], C["primary_dark"])
    button("Success.TButton", "#16a34a", "#15803d")
    button("Warning.TButton", "#d97706", "#b45309")
    button("Danger.TButton", "#dc2626", "#b91c1c")
    button("Violet.TButton", "#7c3aed", "#6d28d9")
    button("Teal.TButton", "#0891b2", "#0e7490")
    button("Ghost.TButton", "#e2e8f0", "#cbd5e1", fg=C["text"])

    style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff",
                    foreground=C["text"], rowheight=int(line * 1.75), borderwidth=0,
                    font=(FONT, 10))
    style.configure("Treeview.Heading", background="#e8edf5", foreground=C["navy"],
                    font=(FONT, 10, "bold"), relief="flat", padding=(6, 5))
    style.map("Treeview", background=[("selected", "#bfdbfe")],
              foreground=[("selected", C["text"])])
    style.configure("Compact.Treeview", rowheight=int(line * 1.35), font=(FONT, 9))
    style.configure("Compact.Treeview.Heading", background="#e8edf5", foreground=C["navy"],
                    font=(FONT, 9, "bold"), relief="flat", padding=(4, 4))
    style.map("Compact.Treeview", background=[("selected", "#bfdbfe")],
              foreground=[("selected", C["text"])])
    style.map("Treeview.Heading", background=[("active", "#dbe4f0")])
    style.configure("TCombobox", padding=4)
    style.configure("Horizontal.TProgressbar", troughcolor="#e2e8f0", background=C["primary"],
                    bordercolor="#e2e8f0", lightcolor=C["primary"], darkcolor=C["primary"])
    style.configure("Vertical.TScrollbar", background="#e2e8f0", troughcolor="#f8fafc",
                    bordercolor="#f8fafc", arrowcolor=C["muted"])
    return style
