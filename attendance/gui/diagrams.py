"""Canvas drawings of the DFA and the attendance FSM (used by the visualizer tabs)."""

import math
import tkinter as tk

from ..dfa import DEAD
from ..fsm import ABSENT, EXCUSED, LATE, NOT_MARKED, ON_DUTY, PRESENT, RESET
from .theme import C, FONT, MONO, STATE_STYLE


def _bezier(p0, c, p2, n=40):
    pts = []
    for i in range(n + 1):
        t = i / n
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * c[0] + t ** 2 * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * c[1] + t ** 2 * p2[1]
        pts.append((x, y))
    return pts


class _Base(tk.Canvas):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg="#ffffff", highlightthickness=0, **kw)
        self.k = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self.bind("<Configure>", lambda e: self.redraw())

    def _label(self, x, y, text, color=C["text"], size=9, bold=False, mono=False, bg="#ffffff"):
        t = self.create_text(x, y, text=text, fill=color,
                             font=(MONO if mono else FONT, size, "bold" if bold else "normal"))
        if bg:
            x0, y0, x1, y1 = self.bbox(t)
            r = self.create_rectangle(x0 - 3, y0 - 1, x1 + 3, y1 + 1, fill=bg, outline="")
            self.tag_lower(r, t)
        return t

    def redraw(self):  # pragma: no cover - overridden
        pass


class DFADiagram(_Base):
    """Draws M and animates a run over an input tape."""

    def __init__(self, parent, dfa, compact=False, **kw):
        self.dfa = dfa
        self.trace = None
        self.consumed = 0
        self.finished = False
        self.compact = compact  # small version without the tape (Register tab)
        super().__init__(parent, **kw)

    def set_dfa(self, dfa):
        self.dfa = dfa
        self.clear_run()

    def clear_run(self):
        self.trace, self.consumed, self.finished = None, 0, False
        self.redraw()

    def show_run(self, trace, consumed, finished):
        self.trace, self.consumed, self.finished = trace, consumed, finished
        self.redraw()

    # ------------------------------------------------------------------
    def _layout(self, W, H):
        k = self.k
        levels = self.dfa.levels()
        by_level = {}
        for q in self.dfa.states:
            by_level.setdefault(levels.get(q, 0), []).append(q)
        depth = max(by_level) if by_level else 1
        widest = max(len(qs) for qs in by_level.values()) if by_level else 1
        mx = (30 if self.compact else 62) * k
        step = (W - 2 * mx) / max(1, depth)
        r_step = max(10 * k, min(23 * k, step * 0.3))

        def margins(r):
            top = (12 * k if self.compact else 70 * k) + r       # below the input tape
            bottom = r + (14 * k if self.compact else r + 34 * k)  # room for the dead state
            return top, bottom

        r = r_step
        if widest > 1:  # several states share a column: shrink circles until they fit
            for _ in range(12):
                top, bottom = margins(r)
                fit = (H - top - bottom) / (widest - 1) / 2 - 3 * k
                r = (r + min(r_step, max(8 * k, fit))) / 2
        top, bottom = margins(r)
        area = H - top - bottom
        pos = {}
        for lvl, qs in by_level.items():
            for i, q in enumerate(qs):
                frac = 0.5 if len(qs) == 1 else i / (len(qs) - 1)
                pos[q] = (mx + lvl * step, top + area * frac)
        if self.compact:
            return pos, (W - mx, H - r - 4 * k), r
        return pos, (W * 0.42, H - r - 12 * k), r

    def redraw(self):
        self.delete("all")
        W, H = self.winfo_width(), self.winfo_height()
        if W < 50 or H < 50:
            return
        k = self.k
        pos, dead_xy, r = self._layout(W, H)
        tr = self.trace
        path = tr.path[: self.consumed + 1] if tr else []
        taken = {(path[i], path[i + 1]) for i in range(len(path) - 1)}
        current = path[-1] if path else None

        if not self.compact:
            self._draw_tape(W, k)

        # edges
        for src, lbl, dst in self.dfa.edges():
            (x0, y0), (x1, y1) = pos[src], pos[dst]
            d = math.hypot(x1 - x0, y1 - y0) or 1
            ux, uy = (x1 - x0) / d, (y1 - y0) / d
            hot = (src, dst) in taken
            color = C["primary"] if hot else "#64748b"
            self.create_line(x0 + ux * r, y0 + uy * r, x1 - ux * r, y1 - uy * r,
                             arrow="last", fill=color, width=3 if hot else 1.4,
                             arrowshape=(9 * k, 11 * k, 4 * k))
            if self.compact:
                continue  # the small diagram shows states only
            mxp, myp = (x0 + x1) / 2, (y0 + y1) / 2
            self._label(mxp + uy * 11 * k, myp - ux * 11 * k, lbl,
                        color=C["primary_dark"] if hot else C["text"], size=8, mono=True,
                        bold=hot)

        # start arrow
        sx, sy = pos[self.dfa.start]
        reach = (18 if self.compact else 34) * k
        self.create_line(sx - r - reach, sy, sx - r, sy, arrow="last", width=2,
                         fill=C["navy"], arrowshape=(9 * k, 11 * k, 4 * k))
        if not self.compact:
            self.create_text(sx - r - reach, sy - 11 * k, text="start", anchor="w",
                             fill=C["navy"], font=(FONT, 8, "bold"))

        # dead state
        dx, dy = dead_xy
        hit_dead = current == DEAD
        if hit_dead and self.compact and len(path) >= 2:
            # small view: draw qd just below the state that failed, so the arrow stays clear
            dx = min(pos[path[-2]][0] + 1.8 * r, W - r - 2)
            dy = H - r - 3 * k
        self.create_oval(dx - r, dy - r, dx + r, dy + r, dash=(4, 3), width=2,
                         outline=C["danger"] if hit_dead else "#94a3b8",
                         fill="#fecaca" if hit_dead else "#f8fafc")
        self.create_text(dx, dy, text=DEAD, font=(FONT, 9 if self.compact else 10, "bold"),
                         fill=C["danger"] if hit_dead else "#64748b")
        if not self.compact:
            self.create_text(dx + r + 8 * k, dy, anchor="w", fill="#64748b", font=(FONT, 8),
                             text="dead (trap) state: every missing transition goes here")
        if hit_dead and len(path) >= 2:
            src = path[-2]
            x0, y0 = pos[src]
            d = math.hypot(dx - x0, dy - y0) or 1
            ux, uy = (dx - x0) / d, (dy - y0) / d
            self.create_line(x0 + ux * r, y0 + uy * r, dx - ux * r, dy - uy * r, arrow="last",
                             fill=C["danger"], width=3, dash=(6, 4),
                             arrowshape=(9 * k, 11 * k, 4 * k))
            bad = tr.steps[self.consumed - 1].symbol
            self._label((x0 + dx) / 2 + 14 * k, (y0 + dy) / 2, f"'{bad}'", color=C["danger"],
                        size=9, bold=True, mono=True)

        # states
        visited = set(path)
        for q, (x, y) in pos.items():
            fill, outline, width = "#ffffff", C["navy"], 2
            if q in visited:
                fill = "#dbeafe"
            if q == current:
                if self.finished:
                    good = tr.accepted
                    fill = "#bbf7d0" if good else "#fecaca"
                    outline = C["success"] if good else C["danger"]
                else:
                    fill, outline = "#fde68a", "#d97706"
                width = 3
            self.create_oval(x - r, y - r, x + r, y + r, fill=fill, outline=outline, width=width)
            if q in self.dfa.accept:
                g = 4 * k
                self.create_oval(x - r + g, y - r + g, x + r - g, y + r - g, outline=outline,
                                 width=1.5)
            size = 8 if self.compact or r < 18 * k else 9
            if r < 13 * k:
                size = 7
            self.create_text(x, y, text=q, font=(FONT, size, "bold"), fill=C["text"])

    def _draw_tape(self, W, k):
        tr = self.trace
        self.create_text(14 * k, 16 * k, anchor="w", text="Input tape", fill=C["muted"],
                         font=(FONT, 9, "bold"))
        if tr is None:
            self.create_text(14 * k, 40 * k, anchor="w", fill="#94a3b8", font=(FONT, 9),
                             text="Type a string below and press Run to watch the DFA read it "
                                  "symbol by symbol.")
            return
        text = tr.text or "ε"
        box = min(30 * k, (W - 330 * k) / max(1, len(text)))
        x0, y0 = 100 * k, 28 * k
        for i, ch in enumerate(text):
            if i < self.consumed:
                fill = "#fecaca" if tr.error_position == i else "#e2e8f0"
            elif i == self.consumed and not self.finished:
                fill = "#fde68a"
            else:
                fill = "#ffffff"
            self.create_rectangle(x0 + i * box, y0, x0 + (i + 1) * box, y0 + box, fill=fill,
                                  outline="#94a3b8")
            self.create_text(x0 + (i + 0.5) * box, y0 + box / 2, text=ch,
                             font=(MONO, 11, "bold"), fill=C["text"])
        if not self.finished:
            hx = x0 + (self.consumed + 0.5) * box
            self.create_text(hx, y0 - 7 * k, text="▼", fill="#d97706", font=(FONT, 9))
        if self.finished:
            msg, color = (("ACCEPTED ✔", C["success"]) if tr.accepted else ("REJECTED ✖", C["danger"]))
        else:
            state = tr.path[self.consumed] if self.consumed < len(tr.path) else "?"
            msg, color = f"reading…  current state {state}", "#b45309"
        self.create_text(W - 14 * k, 16 * k, anchor="e", text=msg, fill=color,
                         font=(FONT, 12, "bold"))


class FSMDiagram(_Base):
    """Draws the attendance FSM and highlights a student's state / last move."""

    POS = {NOT_MARKED: (0.15, 0.5), PRESENT: (0.46, 0.25), LATE: (0.46, 0.5),
           ABSENT: (0.46, 0.75), EXCUSED: (0.84, 0.3), ON_DUTY: (0.84, 0.7)}
    # (source, target, event, relative control point or None, label position t)
    EDGES = [
        (NOT_MARKED, PRESENT, "MARK_ON_TIME", None, 0.45),
        (NOT_MARKED, LATE, "MARK_LATE", None, 0.5),
        (NOT_MARKED, ABSENT, "TIMEOUT", None, 0.45),
        (NOT_MARKED, EXCUSED, "EXCUSE", (0.45, -0.27), 0.5),
        (NOT_MARKED, ON_DUTY, "GRANT_OD", (0.45, 1.27), 0.5),
        (LATE, EXCUSED, "EXCUSE", None, 0.5),
        (LATE, ON_DUTY, "GRANT_OD", None, 0.72),
        (ABSENT, EXCUSED, "EXCUSE", None, 0.17),
        (ABSENT, ON_DUTY, "GRANT_OD", None, 0.5),
    ]

    def __init__(self, parent, **kw):
        self.current = NOT_MARKED
        self.last = None
        super().__init__(parent, **kw)

    def set_state(self, current, last=None):
        self.current, self.last = current, last
        self.redraw()

    def redraw(self):
        self.delete("all")
        W, H = self.winfo_width(), self.winfo_height()
        if W < 50 or H < 50:
            return
        k = self.k
        rx, ry = min(70 * k, W * 0.085), min(25 * k, H * 0.07)
        xy = {s: (px * W, py * H) for s, (px, py) in self.POS.items()}

        def inside(p, s):
            cx, cy = xy[s]
            return ((p[0] - cx) / (rx + 2)) ** 2 + ((p[1] - cy) / (ry + 2)) ** 2 < 1

        for src, dst, event, ctrl, t_lbl in self.EDGES:
            p0, p2 = xy[src], xy[dst]
            c = (ctrl[0] * W, ctrl[1] * H) if ctrl else ((p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2)
            pts = [p for p in _bezier(p0, c, p2) if not inside(p, src) and not inside(p, dst)]
            if len(pts) < 2:
                continue
            hot = (self.last is not None and self.last.source == src
                   and self.last.target == dst and self.last.event == event)
            color = C["primary"] if hot else "#64748b"
            self.create_line(*[v for p in pts for v in p], arrow="last", fill=color,
                             width=3.2 if hot else 1.5, smooth=True,
                             arrowshape=(10 * k, 12 * k, 4 * k))
            lx, ly = _bezier(p0, c, p2, 100)[int(t_lbl * 100)]
            self._label(lx, ly, event, color=C["primary_dark"] if hot else C["text"], size=8,
                        mono=True, bold=hot)

        sx, sy = xy[NOT_MARKED]
        self.create_line(sx - rx - 36 * k, sy, sx - rx, sy, arrow="last", width=2, fill=C["navy"],
                         arrowshape=(9 * k, 11 * k, 4 * k))
        self.create_text(sx - rx - 36 * k, sy - 12 * k, anchor="w", text="start",
                         fill=C["navy"], font=(FONT, 8, "bold"))

        for s, (x, y) in xy.items():
            bg, fg, _ = STATE_STYLE[s]
            cur = s == self.current
            if cur:
                g = 6 * k
                self.create_oval(x - rx - g, y - ry - g, x + rx + g, y + ry + g, fill="#fef08a",
                                 outline="#eab308", width=2)
            self.create_oval(x - rx, y - ry, x + rx, y + ry, fill=bg,
                             outline=fg if cur else "#94a3b8", width=3 if cur else 1.5)
            self.create_text(x, y, text=s, fill=fg, font=(FONT, 9, "bold"))

        if self.last is not None and self.last.event == RESET:
            self._label(sx, sy + ry + 12 * k, "← RESET (undo)", color=C["primary_dark"], size=8,
                        bold=True)
