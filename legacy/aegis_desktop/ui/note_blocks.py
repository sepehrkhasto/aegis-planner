# SPDX-License-Identifier: GPL-3.0-or-later
"""Blocks that live inside a note, between its paragraphs: a hand-drawn sketch and a flowchart.

Both are vector and tiny: a sketch is a list of strokes (points on a 1000-unit-wide page), a flowchart is nodes and edges.
They are stored inside the encrypted vault with the note (``note["blocks"]``), cost nothing while idle (no timers; a
committed drawing is cached as one pixmap) and can paint themselves onto any QPainter (``render``) for export and for
the gallery thumbnails.

``InkCanvas``   pen / marker / eraser, pressure from a stylus, undo / redo, resizable page, dots / lines / grid paper.
``FlowCanvas``  five shapes, arrows that follow their nodes, drag from a node's port to a node (or to empty space to create
                the next step), double-click to type, auto-tidy layout, fit-to-width scaling.
``BlockFrame``  the card around a block: title, its tools, move up / down, delete.
"""
from __future__ import annotations

import copy
import math

from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
                         QTextOption)
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QSizePolicy, QVBoxLayout, QWidget)

from .fx_widgets import _fpal
from .notes_ui import ColorDot, FlatIconButton
from .premium import alpha
from .theme import rr

W_UNITS = 1000.0                                   # a sketch page is always 1000 units wide, whatever the widget's width
INK_COLORS = ("text", "accent2", "danger", "ok", "warn", "accent")
INK_NAMES = {"text": "مداد", "accent2": "آبی", "danger": "قرمز", "ok": "سبز", "warn": "زرد", "accent": "برند"}
PRINT_PAL = {"bg": "#ffffff", "panel": "#ffffff", "panel2": "#f3f4f6", "line": "#c9ced6", "text": "#15171c", "muted": "#6b7280",
             "accent": "#25262b", "accent2": "#2c5fd0", "danger": "#d33a46", "ok": "#1f9d6a", "warn": "#d99a14",
             "acc_text": "#15171c", "edge": "#9aa1ac", "soft": "#eef0f3", "hi": "#ffffff", "ink": "#ffffff"}
MAX_POINTS = 60_000                                # total points one sketch may hold (a hand-edited file cannot hang the UI)
MAX_STROKES = 4_000
MAX_NODES = 300


def ink_color(key: str, pal: dict) -> QColor:
    if isinstance(key, str) and key.startswith("#") and QColor(key).isValid():
        return QColor(key)
    return QColor(pal.get(key if key in pal else "text", pal["text"]))


def clean_ink(d: dict) -> dict:
    """A sketch dict from the vault, repaired: wrong types dropped, coordinates clamped, size limits enforced."""
    out = {"t": "ink", "id": str(d.get("id") or ""), "h": 300, "bg": "dots", "strokes": []}
    try:
        out["h"] = max(120, min(2400, int(d.get("h", 300))))
    except (TypeError, ValueError):
        pass
    if d.get("bg") in ("blank", "dots", "lines", "grid"):
        out["bg"] = d["bg"]
    budget = MAX_POINTS
    for s in (d.get("strokes") if isinstance(d.get("strokes"), list) else [])[:MAX_STROKES]:
        if not isinstance(s, dict) or not isinstance(s.get("p"), list):
            continue
        pts = [v for v in s["p"] if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) < 1e6]
        pts = pts[: len(pts) // 2 * 2][: max(0, budget * 2)]
        if not pts:
            continue
        budget -= len(pts) // 2
        st = {"c": s.get("c") if isinstance(s.get("c"), str) else "text", "w": 2.4, "m": 1 if s.get("m") else 0,
              "p": [round(float(v), 1) for v in pts]}
        try:
            st["w"] = max(0.4, min(60.0, float(s.get("w", 2.4))))
        except (TypeError, ValueError):
            pass
        q = s.get("q")
        if isinstance(q, list) and len(q) == len(pts) // 2 and all(isinstance(v, (int, float)) for v in q):
            st["q"] = [int(max(1, min(100, v))) for v in q]
        out["strokes"].append(st)
        if budget <= 0:
            break
    return out


def paint_strokes(p: QPainter, strokes: list, s: float, pal: dict) -> None:
    """Draw ``strokes`` scaled by ``s`` (page units -> pixels) in the palette ``pal``."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for st in strokes:
        pts = st["p"]
        n = len(pts) // 2
        if n == 0:
            continue
        col = ink_color(st.get("c", "text"), pal)
        marker = bool(st.get("m"))
        w = float(st.get("w", 2.4)) * (4.2 if marker else 1.0) * s
        if marker:
            col.setAlphaF(0.36)
        q = st.get("q")
        if n == 1:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(pts[0] * s, pts[1] * s), w / 2, w / 2)
            p.setBrush(Qt.BrushStyle.NoBrush)
            continue
        if q:                                                  # a stylus stroke: the line swells with the pressure
            for i in range(1, n):
                pen = QPen(col, max(0.5, w * (0.35 + 0.9 * (q[i - 1] + q[i]) / 200.0)))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawLine(QPointF(pts[2 * i - 2] * s, pts[2 * i - 1] * s), QPointF(pts[2 * i] * s, pts[2 * i + 1] * s))
            continue
        pen = QPen(col, max(0.5, w))
        pen.setCapStyle(Qt.PenCapStyle.FlatCap if marker else Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        path = QPainterPath(QPointF(pts[0] * s, pts[1] * s))
        for i in range(1, n - 1):                              # quadratic smoothing through the midpoints
            x1, y1 = pts[2 * i] * s, pts[2 * i + 1] * s
            x2, y2 = (pts[2 * i] + pts[2 * i + 2]) / 2 * s, (pts[2 * i + 1] + pts[2 * i + 3]) / 2 * s
            path.quadTo(x1, y1, x2, y2)
        path.lineTo(pts[2 * n - 2] * s, pts[2 * n - 1] * s)
        p.drawPath(path)
    p.restore()


def paint_paper(p: QPainter, rect: QRectF, bg: str, s: float, pal: dict) -> None:
    """Dots / lines / grid on the page; the pattern scales with the page so a drawing never drifts off it."""
    if bg == "blank":
        return
    p.save()
    step = 40.0 * s
    col = alpha(pal["muted"], 0.30 if bg == "dots" else 0.16)
    if step < 6:
        p.restore()
        return
    if bg == "dots":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        y = rect.top() + step
        while y < rect.bottom():
            x = rect.left() + step
            while x < rect.right():
                p.drawEllipse(QPointF(x, y), 1.1, 1.1)
                x += step
            y += step
    else:
        p.setPen(QPen(col, 1))
        y = rect.top() + step
        while y < rect.bottom():
            p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step
        if bg == "grid":
            x = rect.left() + step
            while x < rect.right():
                p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
                x += step
    p.restore()


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


class InkCanvas(QWidget):
    """The sketch page. Strokes are kept in page units, so the same drawing fits any width."""

    changed = pyqtSignal()

    def __init__(self, data: dict | None = None, parent=None):
        super().__init__(parent)
        self.theme = None                             # (set by the frame; _fpal falls back to ancestors)
        self.strokes: list[dict] = []
        self.h = 300
        self.bg = "dots"
        self.tool, self.color, self.pen_w = "pen", "text", 2.4
        self._cur: dict | None = None
        self._erasing = False
        self._erased = False
        self._undo: list[list] = []
        self._redo: list[list] = []
        self._cache: QPixmap | None = None
        self._cache_key = None
        self._grip_drag = False
        self._tablet = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if data:
            self.set_data(data)
        self._fit()

    # data --------------------------------------------------------------------
    def data(self) -> dict:
        return {"t": "ink", "h": int(self.h), "bg": self.bg, "strokes": [dict(s) for s in self.strokes]}

    def set_data(self, d: dict) -> None:
        c = clean_ink(d)
        self.strokes, self.h, self.bg = c["strokes"], c["h"], c["bg"]
        self._undo.clear()
        self._redo.clear()
        self._cache = None
        self._fit()
        self.update()

    def is_empty(self) -> bool:
        return not self.strokes

    # geometry ----------------------------------------------------------------
    def _s(self) -> float:
        return max(0.2, self.width_px() / W_UNITS)

    def width_px(self) -> int:
        return max(1, self.width() if self.width() > 20 else 800)

    def _fit(self) -> None:
        self.setFixedHeight(max(90, int(self.h * self._s())))

    def sizeHint(self):  # noqa: N802
        from PyQt6.QtCore import QSize
        return QSize(600, int(self.h * 0.6))

    def resizeEvent(self, e) -> None:  # noqa: N802
        self._cache = None
        self._fit()
        super().resizeEvent(e)

    # tools -------------------------------------------------------------------
    def set_tool(self, tool: str) -> None:
        self.tool = tool if tool in ("pen", "marker", "eraser") else "pen"
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_color(self, key: str) -> None:
        self.color = key
        if self.tool == "eraser":
            self.set_tool("pen")

    def set_width(self, w: float) -> None:
        self.pen_w = max(0.6, float(w))

    def set_bg(self, bg: str) -> None:
        if bg in ("blank", "dots", "lines", "grid") and bg != self.bg:
            self.bg = bg
            self.update()
            self.changed.emit()

    def _push_undo(self) -> None:
        self._undo.append(list(self.strokes))
        del self._undo[:-60]
        self._redo.clear()

    def undo(self) -> None:
        if self._undo:
            self._redo.append(list(self.strokes))
            self.strokes = self._undo.pop()
            self._cache = None
            self.update()
            self.changed.emit()

    def redo(self) -> None:
        if self._redo:
            self._undo.append(list(self.strokes))
            self.strokes = self._redo.pop()
            self._cache = None
            self.update()
            self.changed.emit()

    def clear(self) -> None:
        if self.strokes:
            self._push_undo()
            self.strokes = []
            self._cache = None
            self.update()
            self.changed.emit()

    # input -------------------------------------------------------------------
    def _logical(self, pos) -> tuple[float, float]:
        s = self._s()
        return pos.x() / s, pos.y() / s

    def _in_grip(self, pos) -> bool:
        return pos.y() >= self.height() - 14 and pos.x() > self.width() / 2 - 60 and pos.x() < self.width() / 2 + 60

    def _begin(self, pos, pressure: float = -1.0, eraser: bool = False) -> None:
        x, y = self._logical(pos)
        self._erasing = eraser or self.tool == "eraser"
        if self._erasing:
            self._erased = False
            self._undo_pending = list(self.strokes)
            self._erase_at(x, y)
            return
        self._cur = {"c": self.color, "w": self.pen_w, "m": 1 if self.tool == "marker" else 0, "p": [round(x, 1), round(y, 1)]}
        if pressure >= 0:
            self._cur["q"] = [int(max(1, min(100, pressure * 100)))]
        self.update()

    def _move(self, pos, pressure: float = -1.0) -> None:
        x, y = self._logical(pos)
        if self._erasing:
            self._erase_at(x, y)
            return
        if self._cur is None:
            return
        pts = self._cur["p"]
        if math.hypot(x - pts[-2], y - pts[-1]) < 1.3:           # drop jitter: a smooth line needs far fewer points
            return
        if sum(len(s["p"]) for s in self.strokes[-200:]) // 2 + len(pts) // 2 > MAX_POINTS:
            return
        pts.extend((round(x, 1), round(y, 1)))
        if "q" in self._cur:
            self._cur["q"].append(int(max(1, min(100, (pressure if pressure >= 0 else 0.5) * 100))))
        self.update()

    def _end(self) -> None:
        if self._erasing:
            if self._erased:
                self._undo.append(self._undo_pending)
                del self._undo[:-60]
                self._redo.clear()
                self._cache = None
                self.update()
                self.changed.emit()
            self._erasing = False
            return
        st, self._cur = self._cur, None
        if st is None or len(self.strokes) >= MAX_STROKES:
            return
        q = st.get("q")
        if q and max(q) - min(q) < 6:                              # a steady stylus pressure is just a plain line
            del st["q"]
        self._push_undo()
        self.strokes.append(st)
        self._paint_into_cache(st)
        self.update()
        self.changed.emit()

    def _erase_at(self, x: float, y: float) -> None:
        r = 16.0
        keep = []
        for st in self.strokes:
            pts, hit = st["p"], False
            if len(pts) == 2:
                hit = math.hypot(x - pts[0], y - pts[1]) <= r
            else:
                for i in range(0, len(pts) - 2, 2):
                    if _seg_dist(x, y, pts[i], pts[i + 1], pts[i + 2], pts[i + 3]) <= r:
                        hit = True
                        break
            if not hit:
                keep.append(st)
        if len(keep) != len(self.strokes):
            self.strokes = keep
            self._erased = True
            self._cache = None
            self.update()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() != Qt.MouseButton.LeftButton or self._tablet:
            return
        if self._in_grip(e.position()):
            self._grip_drag = True
            return
        self._begin(e.position())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._grip_drag:
            self.h = max(120, min(2400, e.position().y() / self._s()))
            self._fit()
            self._cache = None
            self.update()
            return
        if self._in_grip(e.position()) and not (e.buttons() & Qt.MouseButton.LeftButton):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif not (e.buttons() & Qt.MouseButton.LeftButton):
            self.setCursor(Qt.CursorShape.CrossCursor)
        if e.buttons() & Qt.MouseButton.LeftButton and not self._tablet:
            self._move(e.position())

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._grip_drag:
            self._grip_drag = False
            self.changed.emit()
            return
        if e.button() == Qt.MouseButton.LeftButton and not self._tablet:
            self._end()

    def tabletEvent(self, e) -> None:  # noqa: N802
        """A stylus: pressure sets the line's weight, the pen's eraser end erases."""
        from PyQt6.QtGui import QPointingDevice
        t = e.type()
        eraser = e.pointerType() == QPointingDevice.PointerType.Eraser
        if t == QEvent.Type.TabletPress:
            self._tablet = True
            self._begin(e.position(), e.pressure(), eraser)
        elif t == QEvent.Type.TabletMove and self._tablet:
            self._move(e.position(), e.pressure())
        elif t == QEvent.Type.TabletRelease and self._tablet:
            self._end()
            self._tablet = False
        e.accept()

    # painting ----------------------------------------------------------------
    def _paint_into_cache(self, st: dict) -> None:
        if self._cache is None:
            return
        p = QPainter(self._cache)
        p.scale(self._cache.devicePixelRatio(), self._cache.devicePixelRatio())
        paint_strokes(p, [st], self._s(), _fpal(self))
        p.end()

    def _build_cache(self) -> None:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        self._cache = pm
        p = QPainter(pm)
        p.scale(dpr, dpr)
        paint_strokes(p, self.strokes, self._s(), _fpal(self))
        p.end()
        self._cache_key = (self.width(), self.height(), id(_fpal(self)))

    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        paint_paper(p, r, self.bg, self._s(), pal)
        key = (self.width(), self.height(), id(pal))
        if self._cache is None or self._cache_key != key:
            self._build_cache()
        p.drawPixmap(0, 0, self._cache)
        if self._cur is not None:
            paint_strokes(p, [self._cur], self._s(), pal)
        gx, gy = self.width() / 2, self.height() - 6
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alpha(pal["muted"], 0.45))
        for dx in (-9, 0, 9):
            p.drawEllipse(QPointF(gx + dx, gy), 1.6, 1.6)

    def render(self, p: QPainter, rect: QRectF, pal: dict, paper: bool = True) -> float:
        """Paint the sketch into ``rect`` (width decides the scale); returns the height it needs."""
        s = rect.width() / W_UNITS
        p.save()
        p.translate(rect.topLeft())
        if paper:
            paint_paper(p, QRectF(0, 0, rect.width(), self.h * s), self.bg, s, pal)
        paint_strokes(p, self.strokes, s, pal)
        p.restore()
        return self.h * s


# ------------------------------------------------------------------------------------------------ flowchart ---------

NODE_KINDS = {"start": ("شروع/پایان", "n_start", 150, 48), "proc": ("مرحله", "n_proc", 170, 58),
              "dec": ("تصمیم", "n_dec", 180, 92), "io": ("ورودی/خروجی", "n_io", 180, 58)}
PORT_HIT = 10.0


def clean_flow(d: dict) -> dict:
    out = {"t": "flow", "id": str(d.get("id") or ""), "nodes": [], "edges": []}
    seen: set[str] = set()
    for n in (d.get("nodes") if isinstance(d.get("nodes"), list) else [])[:MAX_NODES]:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or "")
        if not nid or nid in seen:
            continue
        k = n.get("k") if n.get("k") in NODE_KINDS else "proc"
        try:
            x, y = float(n.get("x", 0)), float(n.get("y", 0))
            w, h = float(n.get("w", NODE_KINDS[k][2])), float(n.get("h", NODE_KINDS[k][3]))
        except (TypeError, ValueError):
            continue
        if not all(map(math.isfinite, (x, y, w, h))):
            continue
        seen.add(nid)
        out["nodes"].append({"id": nid, "k": k, "x": max(-5000.0, min(5000.0, x)), "y": max(0.0, min(20000.0, y)),
                             "w": max(60.0, min(420.0, w)), "h": max(34.0, min(300.0, h)), "t": str(n.get("t") or "")[:400]})
    pairs: set[tuple[str, str]] = set()
    for e in (d.get("edges") if isinstance(d.get("edges"), list) else [])[: MAX_NODES * 3]:
        if not isinstance(e, dict):
            continue
        a, b = str(e.get("a")), str(e.get("b"))
        if a in seen and b in seen and a != b and (a, b) not in pairs:
            pairs.add((a, b))
            out["edges"].append({"a": a, "b": b, "l": str(e.get("l") or "")[:60]})
    return out


def _bezier_pt(p0: QPointF, c1: QPointF, c2: QPointF, p1: QPointF, t: float) -> QPointF:
    u = 1 - t
    return QPointF(u ** 3 * p0.x() + 3 * u * u * t * c1.x() + 3 * u * t * t * c2.x() + t ** 3 * p1.x(),
                   u ** 3 * p0.y() + 3 * u * u * t * c1.y() + 3 * u * t * t * c2.y() + t ** 3 * p1.y())


class FlowCanvas(QWidget):
    changed = pyqtSignal()

    MARGIN_TOP, MARGIN_BOTTOM, MIN_H = 30.0, 44.0, 260

    def __init__(self, data: dict | None = None, parent=None):
        super().__init__(parent)
        self.theme = None
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.sel_node: str | None = None
        self.sel_edge: tuple[str, str] | None = None
        self.hover: str | None = None
        self._drag: tuple[str, QPointF] | None = None
        self._drag_moved = False
        self._link: tuple[str, int] | None = None
        self._link_pos = QPointF()
        self._edit: QLineEdit | None = None
        self._edit_id: str | None = None
        self._undo: list[tuple] = []
        self._redo: list[tuple] = []
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if data:
            self.set_data(data)
        self._fit()

    # data --------------------------------------------------------------------
    def data(self) -> dict:
        return {"t": "flow", "nodes": copy.deepcopy(self.nodes), "edges": copy.deepcopy(self.edges)}

    def set_data(self, d: dict) -> None:
        c = clean_flow(d)
        self.nodes, self.edges = c["nodes"], c["edges"]
        self.sel_node = self.sel_edge = None
        self._undo.clear()
        self._redo.clear()
        self._fit()
        self.update()

    def is_empty(self) -> bool:
        return not self.nodes

    def _snap(self) -> tuple:
        return copy.deepcopy(self.nodes), copy.deepcopy(self.edges)

    def _checkpoint(self) -> None:
        self._undo.append(self._snap())
        del self._undo[:-50]
        self._redo.clear()

    def undo(self) -> None:
        if self._undo:
            self._redo.append(self._snap())
            self.nodes, self.edges = self._undo.pop()
            self.sel_node = self.sel_edge = None
            self._after_change()

    def redo(self) -> None:
        if self._redo:
            self._undo.append(self._snap())
            self.nodes, self.edges = self._redo.pop()
            self.sel_node = self.sel_edge = None
            self._after_change()

    def _after_change(self) -> None:
        self._close_edit()
        self._fit()
        self.update()
        self.changed.emit()

    def clear(self) -> None:
        if self.nodes:
            self._checkpoint()
            self.nodes, self.edges = [], []
            self.sel_node = self.sel_edge = None
            self._after_change()

    # geometry ----------------------------------------------------------------
    def _node(self, nid: str) -> dict | None:
        return next((n for n in self.nodes if n["id"] == nid), None)

    def _scale(self) -> float:
        half = max([abs(n["x"]) + n["w"] / 2 for n in self.nodes] or [1.0])
        return max(0.35, min(1.0, (max(self.width(), 300) - 36) / (2 * half)))

    def _origin(self) -> QPointF:
        return QPointF(max(self.width(), 300) / 2, self.MARGIN_TOP)

    def _to_view(self, x: float, y: float) -> QPointF:
        o, s = self._origin(), self._scale()
        return QPointF(o.x() + x * s, o.y() + y * s)

    def _to_model(self, pt: QPointF) -> QPointF:
        o, s = self._origin(), self._scale()
        return QPointF((pt.x() - o.x()) / s, (pt.y() - o.y()) / s)

    def _fit(self) -> None:
        bottom = max([n["y"] + n["h"] / 2 for n in self.nodes] or [0.0])
        self.setFixedHeight(int(max(self.MIN_H, self.MARGIN_TOP + bottom * self._scale() + self.MARGIN_BOTTOM)))

    def sizeHint(self):  # noqa: N802
        from PyQt6.QtCore import QSize
        return QSize(600, self.MIN_H)

    def resizeEvent(self, e) -> None:  # noqa: N802
        self._fit()
        self._place_edit()
        super().resizeEvent(e)

    def _rect(self, n: dict) -> QRectF:
        return QRectF(n["x"] - n["w"] / 2, n["y"] - n["h"] / 2, n["w"], n["h"])

    def _ports(self, n: dict) -> list[QPointF]:
        """Model-space ports: top, right, bottom, left."""
        x, y, w, h = n["x"], n["y"], n["w"], n["h"]
        return [QPointF(x, y - h / 2), QPointF(x + w / 2, y), QPointF(x, y + h / 2), QPointF(x - w / 2, y)]

    @staticmethod
    def _dir(side: int) -> QPointF:
        return (QPointF(0, -1), QPointF(1, 0), QPointF(0, 1), QPointF(-1, 0))[side]

    def _edge_sides(self, a: dict, b: dict) -> tuple[int, int]:
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        if abs(dy) >= abs(dx) * 0.55:
            return (2, 0) if dy >= 0 else (0, 2)
        return (1, 3) if dx >= 0 else (3, 1)

    def _edge_curve(self, a: dict, b: dict) -> tuple[QPointF, QPointF, QPointF, QPointF]:
        sa, sb = self._edge_sides(a, b)
        p0, p1 = self._ports(a)[sa], self._ports(b)[sb]
        off = max(36.0, math.hypot(p1.x() - p0.x(), p1.y() - p0.y()) * 0.38)
        da, db = self._dir(sa), self._dir(sb)
        return p0, QPointF(p0.x() + da.x() * off, p0.y() + da.y() * off), QPointF(p1.x() + db.x() * off, p1.y() + db.y() * off), p1

    # hit tests ---------------------------------------------------------------
    def _node_at(self, pt: QPointF) -> dict | None:
        m = self._to_model(pt)
        for n in reversed(self.nodes):
            if self._rect(n).adjusted(-3, -3, 3, 3).contains(m):
                return n
        return None

    def _port_at(self, pt: QPointF, n: dict) -> int | None:
        s = self._scale()
        for i, pp in enumerate(self._ports(n)):
            v = self._to_view(pp.x(), pp.y())
            if math.hypot(v.x() - pt.x(), v.y() - pt.y()) <= PORT_HIT + 2 * s:
                return i
        return None

    def _edge_at(self, pt: QPointF) -> tuple[str, str] | None:
        m = self._to_model(pt)
        for e in self.edges:
            a, b = self._node(e["a"]), self._node(e["b"])
            if not a or not b:
                continue
            p0, c1, c2, p1 = self._edge_curve(a, b)
            prev = p0
            for i in range(1, 25):
                q = _bezier_pt(p0, c1, c2, p1, i / 24)
                if _seg_dist(m.x(), m.y(), prev.x(), prev.y(), q.x(), q.y()) <= 9:
                    return e["a"], e["b"]
                prev = q
        return None

    # editing the graph -------------------------------------------------------
    def _new_id(self) -> str:
        used = {n["id"] for n in self.nodes}
        i = len(used) + 1
        while f"n{i}" in used:
            i += 1
        return f"n{i}"

    def add_node(self, kind: str = "proc", x: float | None = None, y: float | None = None, text: str = "",
                 link_from: str | None = None) -> dict:
        kind = kind if kind in NODE_KINDS else "proc"
        _lab, _ic, w, h = NODE_KINDS[kind]
        if x is None or y is None:
            ref = self._node(self.sel_node) if self.sel_node else (self.nodes[-1] if self.nodes else None)
            if ref is not None:
                x, y = ref["x"], ref["y"] + ref["h"] / 2 + 70 + h / 2
            else:
                x, y = 0.0, h / 2 + 4
        self._checkpoint()
        n = {"id": self._new_id(), "k": kind, "x": round(x / 10) * 10.0, "y": max(h / 2, round(y / 10) * 10.0), "w": float(w),
             "h": float(h), "t": text}
        if len(self.nodes) < MAX_NODES:
            self.nodes.append(n)
        src = link_from or (self.sel_node if self.nodes[:-1] else None)
        if src and src != n["id"] and self._node(src) and not any(e["a"] == src and e["b"] == n["id"] for e in self.edges):
            self.edges.append({"a": src, "b": n["id"], "l": ""})
        self.sel_node, self.sel_edge = n["id"], None
        self._after_change()
        return n

    def delete_selected(self) -> None:
        if self.sel_node:
            self._checkpoint()
            self.nodes = [n for n in self.nodes if n["id"] != self.sel_node]
            self.edges = [e for e in self.edges if self.sel_node not in (e["a"], e["b"])]
            self.sel_node = None
            self._after_change()
        elif self.sel_edge:
            self._checkpoint()
            self.edges = [e for e in self.edges if (e["a"], e["b"]) != self.sel_edge]
            self.sel_edge = None
            self._after_change()

    def set_kind(self, nid: str, kind: str) -> None:
        n = self._node(nid)
        if n and kind in NODE_KINDS and n["k"] != kind:
            self._checkpoint()
            n["k"] = kind
            n["w"], n["h"] = float(NODE_KINDS[kind][2]), float(NODE_KINDS[kind][3])
            self._fit_text(n)
            self._after_change()

    def _fit_text(self, n: dict) -> None:
        fm = QFontMetrics(self.font())
        inner_w = n["w"] * (0.62 if n["k"] == "dec" else 0.82)
        br = fm.boundingRect(QRectF(0, 0, inner_w, 2000).toRect(), int(Qt.TextFlag.TextWordWrap), n["t"] or " ")
        need = br.height() / (0.58 if n["k"] == "dec" else 1.0) + 26
        n["h"] = float(max(NODE_KINDS[n["k"]][3], min(300, need)))

    def auto_layout(self) -> None:
        """Layered top-down layout: rank = longest path from the roots (back edges ignored), then spread each rank."""
        if len(self.nodes) < 2:
            return
        ids = [n["id"] for n in self.nodes]
        out: dict[str, list[str]] = {i: [] for i in ids}
        indeg = {i: 0 for i in ids}
        for e in self.edges:
            out[e["a"]].append(e["b"])
        color: dict[str, int] = {}
        back: set[tuple[str, str]] = set()

        def dfs(u: str) -> None:
            stack = [(u, iter(out[u]))]
            color[u] = 1
            while stack:
                node, it = stack[-1]
                for v in it:
                    if color.get(v, 0) == 0:
                        color[v] = 1
                        stack.append((v, iter(out[v])))
                        break
                    if color.get(v) == 1:
                        back.add((node, v))
                else:
                    color[node] = 2
                    stack.pop()
        has_in = {e["b"] for e in self.edges}
        for r in [i for i in ids if i not in has_in] + ids:
            if color.get(r, 0) == 0:
                dfs(r)
        fwd = [(e["a"], e["b"]) for e in self.edges if (e["a"], e["b"]) not in back]
        for _a, b in fwd:
            indeg[b] += 1
        rank = {i: 0 for i in ids}
        queue = [i for i in ids if indeg[i] == 0]
        deg = dict(indeg)
        while queue:
            u = queue.pop(0)
            for a, b in fwd:
                if a == u:
                    rank[b] = max(rank[b], rank[u] + 1)
                    deg[b] -= 1
                    if deg[b] == 0:
                        queue.append(b)
        layers: dict[int, list[str]] = {}
        for i in ids:
            layers.setdefault(rank[i], []).append(i)
        parents: dict[str, list[str]] = {i: [] for i in ids}
        for a, b in fwd:
            parents[b].append(a)
        pos: dict[str, float] = {}
        by_id = {n["id"]: n for n in self.nodes}
        self._checkpoint()
        y = 0.0
        for r in sorted(layers):
            row = layers[r]
            if r > 0:
                row.sort(key=lambda i: (sum(pos.get(p, 0.0) for p in parents[i]) / len(parents[i])) if parents[i] else 0.0)
            width = sum(by_id[i]["w"] for i in row) + 50 * (len(row) - 1)
            x = -width / 2
            hmax = max(by_id[i]["h"] for i in row)
            for i in row:
                n = by_id[i]
                n["x"] = round((x + n["w"] / 2) / 10) * 10.0
                n["y"] = round((y + hmax / 2) / 10) * 10.0
                pos[i] = n["x"]
                x += n["w"] + 50
            y += hmax + 64
        self._after_change()

    # inline text edit --------------------------------------------------------
    def _begin_edit(self, nid: str, edge: tuple[str, str] | None = None) -> None:
        self._close_edit()
        self._edit_id = nid if edge is None else None
        self._edit_edge = edge
        if edge is not None:
            e = next((x for x in self.edges if (x["a"], x["b"]) == edge), None)
            text = e["l"] if e else ""
        else:
            n = self._node(nid)
            if not n:
                return
            text = n["t"]
        le = QLineEdit(self)
        le.setText(text)
        le.setAlignment(Qt.AlignmentFlag.AlignCenter)
        le.setPlaceholderText("متن…" if edge is None else "برچسب (مثلاً بله)")
        le.setMaxLength(400 if edge is None else 60)
        pal = _fpal(self)
        le.setStyleSheet(f"QLineEdit{{background:{pal['panel']};color:{pal['text']};border:1.5px solid {pal['accent2']};"
                         f"border-radius:8px;padding:2px 6px;}}")
        le.editingFinished.connect(self._commit_edit)
        self._edit = le
        self._place_edit()
        le.show()
        le.setFocus()
        le.selectAll()

    def _place_edit(self) -> None:
        le = self._edit
        if le is None:
            return
        if self._edit_id:
            n = self._node(self._edit_id)
            if not n:
                return
            c, s = self._to_view(n["x"], n["y"]), self._scale()
            w = max(110.0, n["w"] * s)
            le.setGeometry(int(c.x() - w / 2), int(c.y() - 15), int(w), 30)
        else:
            a, b = (self._node(k) for k in self._edit_edge)
            if not a or not b:
                return
            p0, c1, c2, p1 = self._edge_curve(a, b)
            m = self._to_view(*(lambda q: (q.x(), q.y()))(_bezier_pt(p0, c1, c2, p1, 0.5)))
            le.setGeometry(int(m.x() - 60), int(m.y() - 14), 120, 28)

    def _commit_edit(self) -> None:
        le, self._edit = self._edit, None
        if le is None:
            return
        text = le.text().strip()
        le.deleteLater()
        if self._edit_id:
            n = self._node(self._edit_id)
            if n and n["t"] != text:
                self._checkpoint()
                n["t"] = text
                self._fit_text(n)
                self._after_change()
        else:
            e = next((x for x in self.edges if (x["a"], x["b"]) == self._edit_edge), None)
            if e and e["l"] != text:
                self._checkpoint()
                e["l"] = text
                self._after_change()
        self.update()
        self.setFocus()

    def _close_edit(self) -> None:
        if self._edit is not None:
            self._commit_edit()

    # input -------------------------------------------------------------------
    def mousePressEvent(self, e) -> None:  # noqa: N802
        self._close_edit()
        self.setFocus()
        pt = e.position()
        if e.button() == Qt.MouseButton.RightButton:
            return
        n = self._node_at(pt)
        if n is None and self.hover:
            h = self._node(self.hover)
            if h and self._port_at(pt, h) is not None:
                n = h
        if n is not None:
            port = self._port_at(pt, n)
            if port is not None:                                  # start an arrow from this port
                self._link = (n["id"], port)
                self._link_pos = pt
                self.sel_node, self.sel_edge = n["id"], None
                self.update()
                return
            self.sel_node, self.sel_edge = n["id"], None
            m = self._to_model(pt)
            self._drag = (n["id"], QPointF(m.x() - n["x"], m.y() - n["y"]))
            self._drag_moved = False
            self.update()
            return
        ed = self._edge_at(pt)
        self.sel_node, self.sel_edge = None, ed
        self.update()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        pt = e.position()
        if self._link is not None:
            self._link_pos = pt
            self.update()
            return
        if self._drag is not None:
            nid, off = self._drag
            n = self._node(nid)
            if n is not None:
                if not self._drag_moved:
                    self._checkpoint()
                    self._drag_moved = True
                m = self._to_model(pt)
                n["x"] = round((m.x() - off.x()) / 10) * 10.0
                n["y"] = max(n["h"] / 2, round((m.y() - off.y()) / 10) * 10.0)
                self._fit()
                self.update()
            return
        h = self._node_at(pt)
        hid = h["id"] if h else None
        if hid != self.hover:
            self.hover = hid
            self.update()
        over_port = h is not None and self._port_at(pt, h) is not None
        self.setCursor(Qt.CursorShape.CrossCursor if over_port else (Qt.CursorShape.SizeAllCursor if h else Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        if self._link is not None:
            src, _port = self._link
            self._link = None
            tgt = self._node_at(e.position())
            if tgt is not None and tgt["id"] != src:
                if not any(x["a"] == src and x["b"] == tgt["id"] for x in self.edges):
                    self._checkpoint()
                    self.edges.append({"a": src, "b": tgt["id"], "l": ""})
                    self._after_change()
            elif tgt is None:                                      # released on empty space: the next step appears there
                m = self._to_model(e.position())
                n = self.add_node("proc", m.x(), m.y(), link_from=src)
                self._begin_edit(n["id"])
            self.update()
            return
        if self._drag is not None:
            moved, self._drag = self._drag_moved, None
            if moved:
                self._after_change()

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        pt = e.position()
        n = self._node_at(pt)
        if n is not None:
            self.sel_node = n["id"]
            self._begin_edit(n["id"])
            return
        ed = self._edge_at(pt)
        if ed:
            self.sel_edge, self.sel_node = ed, None
            self._begin_edit("", ed)
            return
        m = self._to_model(pt)
        n = self.add_node("proc", m.x(), m.y(), link_from=None if not self.nodes else None)
        self._begin_edit(n["id"])

    def keyPressEvent(self, e) -> None:  # noqa: N802
        k = e.key()
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
        elif k == Qt.Key.Key_F2 and self.sel_node:
            self._begin_edit(self.sel_node)
        elif k == Qt.Key.Key_Escape:
            self.sel_node = self.sel_edge = None
            self.update()
        elif k == Qt.Key.Key_Z and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.undo()
        elif k == Qt.Key.Key_Y and e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.redo()
        else:
            super().keyPressEvent(e)

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        from .premium import style_menu
        pt = QPointF(e.pos())
        n = self._node_at(pt)
        ed = None if n else self._edge_at(pt)
        if n is None and ed is None:
            return
        m = style_menu(QMenu(self))
        m.aboutToHide.connect(m.deleteLater)
        if n is not None:
            self.sel_node, self.sel_edge = n["id"], None
            m.addAction("ویرایش متن", lambda: self._begin_edit(n["id"]))
            sub = style_menu(m.addMenu("شکل"))
            for k, (lab, _ic, _w, _h) in NODE_KINDS.items():
                sub.addAction(lab, lambda _=False, k=k, i=n["id"]: self.set_kind(i, k))
            m.addAction("مرحله‌ی بعدی", lambda: self.add_node("proc", link_from=n["id"]))
            m.addSeparator()
            m.addAction("حذف", self.delete_selected)
        else:
            self.sel_edge, self.sel_node = ed, None
            m.addAction("برچسب", lambda: self._begin_edit("", ed))
            m.addAction("برعکس کردن جهت", lambda: self._reverse_edge(ed))
            m.addSeparator()
            m.addAction("حذف", self.delete_selected)
        self.update()
        m.exec(e.globalPos())

    def _reverse_edge(self, key: tuple[str, str]) -> None:
        for x in self.edges:
            if (x["a"], x["b"]) == key and not any((y["a"], y["b"]) == (key[1], key[0]) for y in self.edges):
                self._checkpoint()
                x["a"], x["b"] = x["b"], x["a"]
                self.sel_edge = (x["a"], x["b"])
                self._after_change()
                return

    def leaveEvent(self, e) -> None:  # noqa: N802
        self.hover = None
        self.update()
        super().leaveEvent(e)

    # painting ----------------------------------------------------------------
    def paintEvent(self, _e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint(p, pal, self._origin(), self._scale(), interactive=True)
        if not self.nodes:
            p.setPen(QColor(pal["muted"]))
            f = QFont(self.font())
            p.setFont(f)
            p.drawText(QRectF(0, 0, self.width(), self.height()), Qt.AlignmentFlag.AlignCenter,
                       "با «＋ مرحله» شروع کن، یا روی صفحه دوبار کلیک کن")

    def _paint(self, p: QPainter, pal: dict, origin: QPointF, s: float, interactive: bool) -> None:
        p.save()
        p.translate(origin)
        p.scale(s, s)
        nd = {n["id"]: n for n in self.nodes}
        base_font = QFont(self.font())
        # edges first, nodes on top
        for e in self.edges:
            a, b = nd.get(e["a"]), nd.get(e["b"])
            if not a or not b:
                continue
            sel = interactive and self.sel_edge == (e["a"], e["b"])
            col = QColor(pal["accent2"] if sel else pal["muted"])
            p0, c1, c2, p1 = self._edge_curve(a, b)
            path = QPainterPath(p0)
            path.cubicTo(c1, c2, p1)
            pen = QPen(col, 2.2 if sel else 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            tan = QPointF(p1.x() - c2.x(), p1.y() - c2.y())
            L = math.hypot(tan.x(), tan.y()) or 1.0
            ux, uy = tan.x() / L, tan.y() / L
            tip = p1
            wing = 9.0
            tri = QPolygonF([tip, QPointF(tip.x() - ux * wing + uy * wing * 0.5, tip.y() - uy * wing - ux * wing * 0.5),
                             QPointF(tip.x() - ux * wing - uy * wing * 0.5, tip.y() - uy * wing + ux * wing * 0.5)])
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawPolygon(tri)
            if e["l"]:
                mid = _bezier_pt(p0, c1, c2, p1, 0.5)
                fm = QFontMetrics(base_font)
                tw = fm.horizontalAdvance(e["l"]) + 14
                r = QRectF(mid.x() - tw / 2, mid.y() - 11, tw, 22)
                p.setBrush(QColor(pal["bg"]))
                p.setPen(QPen(QColor(pal["line"]), 1))
                p.drawRoundedRect(r, 11, 11)
                p.setPen(QColor(pal["text"]))
                p.setFont(base_font)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, e["l"])
        if interactive and self._link is not None:
            src = nd.get(self._link[0])
            if src:
                a = self._ports(src)[self._link[1]]
                m = self._to_model(self._link_pos)
                pen = QPen(QColor(pal["accent2"]), 1.8, Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawLine(a, m)
        for n in self.nodes:
            self._paint_node(p, n, pal, interactive, base_font)
        p.restore()

    def _shape(self, n: dict) -> QPainterPath:
        r = self._rect(n)
        path = QPainterPath()
        k = n["k"]
        if k == "start":
            path.addRoundedRect(r, r.height() / 2, r.height() / 2)
        elif k == "dec":
            path.addPolygon(QPolygonF([QPointF(r.center().x(), r.top()), QPointF(r.right(), r.center().y()),
                                       QPointF(r.center().x(), r.bottom()), QPointF(r.left(), r.center().y())]))
            path.closeSubpath()
        elif k == "io":
            sk = min(22.0, r.width() * 0.14)
            path.addPolygon(QPolygonF([QPointF(r.left() + sk, r.top()), QPointF(r.right(), r.top()),
                                       QPointF(r.right() - sk, r.bottom()), QPointF(r.left(), r.bottom())]))
            path.closeSubpath()
        else:
            path.addRoundedRect(r, 10, 10)
        return path

    def _paint_node(self, p: QPainter, n: dict, pal: dict, interactive: bool, font: QFont) -> None:
        sel = interactive and self.sel_node == n["id"]
        hov = interactive and self.hover == n["id"]
        path = self._shape(n)
        tint = {"start": pal["ok"], "dec": pal["warn"], "io": pal["accent2"], "proc": pal["accent"]}[n["k"]]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(alpha("#000000", 0.18))
        p.drawPath(path.translated(0, 3))                                   # soft drop
        fill = QColor(pal["panel2"])
        tf = QColor(tint)
        fill = QColor(int(fill.red() * 0.88 + tf.red() * 0.12), int(fill.green() * 0.88 + tf.green() * 0.12),
                      int(fill.blue() * 0.88 + tf.blue() * 0.12))
        p.setBrush(fill)
        p.setPen(QPen(QColor(pal["accent2"]) if sel else (alpha(tint, 0.75) if hov else alpha(tint, 0.55)), 2.0 if sel else 1.4))
        p.drawPath(path)
        r = self._rect(n)
        inner = r.adjusted(r.width() * (0.2 if n["k"] == "dec" else 0.09), 4, -r.width() * (0.2 if n["k"] == "dec" else 0.09), -4)
        p.setPen(QColor(pal["text"]))
        p.setFont(font)
        opt = QTextOption(Qt.AlignmentFlag.AlignCenter)
        opt.setWrapMode(QTextOption.WrapMode.WordWrap)
        p.drawText(inner, n["t"], opt)
        if interactive and (hov or sel) and self._edit is None:
            p.setBrush(QColor(pal["accent2"]))
            p.setPen(QPen(QColor(pal["bg"]), 1.5))
            for pp in self._ports(n):
                p.drawEllipse(pp, 4.6, 4.6)

    def bounds(self) -> QRectF:
        if not self.nodes:
            return QRectF(0, 0, 1, 1)
        x0 = min(n["x"] - n["w"] / 2 for n in self.nodes)
        x1 = max(n["x"] + n["w"] / 2 for n in self.nodes)
        y0 = min(n["y"] - n["h"] / 2 for n in self.nodes)
        y1 = max(n["y"] + n["h"] / 2 for n in self.nodes)
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def render(self, p: QPainter, rect: QRectF, pal: dict, paper: bool = True) -> float:
        """Paint the flowchart fitted into the width of ``rect``; returns the height used."""
        if not self.nodes:
            return 0.0
        b = self.bounds().adjusted(-16, -16, 16, 16)
        s = min(1.0, rect.width() / b.width())
        h = b.height() * s
        origin = QPointF(rect.left() - b.left() * s + (rect.width() - b.width() * s) / 2, rect.top() - b.top() * s)
        self._paint(p, pal, origin, s, interactive=False)
        return h


    def render_fit(self, p: QPainter, rect: QRectF, pal: dict) -> None:
        """Paint the whole flowchart scaled (up to 1.4x) to fit inside ``rect``, centred - used for thumbnails."""
        if not self.nodes:
            return
        b = self.bounds().adjusted(-10, -10, 10, 10)
        s = min(rect.width() / b.width(), rect.height() / b.height(), 1.4)
        origin = QPointF(rect.center().x() - b.center().x() * s, rect.center().y() - b.center().y() * s)
        self._paint(p, pal, origin, s, interactive=False)


def render_block_pixmap(block: dict, w: int, h: int, pal: dict):
    """A small picture of one block (a sketch cropped to its strokes, a flowchart fitted whole), or None when it is empty."""
    kind = block.get("t")
    dpr = 2.0
    pm = QPixmap(int(w * dpr), int(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    area = QRectF(6, 6, w - 12, h - 12)
    try:
        if kind == "ink":
            d = clean_ink(block)
            if not d["strokes"]:
                return None
            xs = [v for st in d["strokes"] for v in st["p"][0::2]]
            ys = [v for st in d["strokes"] for v in st["p"][1::2]]
            x0, x1, y0, y1 = min(xs) - 8, max(xs) + 8, min(ys) - 8, max(ys) + 8
            s = min(area.width() / max(40.0, x1 - x0), area.height() / max(40.0, y1 - y0), 1.2)
            p.translate(area.center().x() - (x0 + x1) / 2 * s, area.center().y() - (y0 + y1) / 2 * s)
            paint_strokes(p, d["strokes"], s, pal)
        elif kind == "flow":
            c = FlowCanvas(block)
            if c.is_empty():
                return None
            c.render_fit(p, area, pal)
        else:
            return None
    finally:
        p.end()
    return pm


# ------------------------------------------------------------------------------------------------ frame -------------

class BlockFrame(QFrame):
    """The card around a block: a slim header (kind, tools, move, delete) and the canvas."""

    delete_req = pyqtSignal(object)
    move_req = pyqtSignal(object, int)
    changed = pyqtSignal()

    def __init__(self, kind: str, data: dict | None = None, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setObjectName("NoteBlock")
        self.block_id = (data or {}).get("id") or ""
        self.canvas: QWidget = InkCanvas(data) if kind == "ink" else FlowCanvas(data)
        self.canvas.changed.connect(self.changed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 12)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(2)
        self.title = QLabel("طراحی دستی" if kind == "ink" else "فلوچارت")
        self.title.setObjectName("Muted")
        head.addWidget(self.title)
        head.addSpacing(8)
        self.tool_btns: dict[str, FlatIconButton] = {}
        if kind == "ink":
            self._ink_tools(head)
        else:
            self._flow_tools(head)
        head.addStretch(1)
        for key, icon, tip, fn in (("up", "up", "بالاتر", lambda: self.move_req.emit(self, -1)),
                                   ("down", "down", "پایین‌تر", lambda: self.move_req.emit(self, 1))):
            b = FlatIconButton(icon, tip, 28)
            b.clicked.connect(fn)
            head.addWidget(b)
        self.btn_del = FlatIconButton("trash", "حذف این بلوک", 28, danger=True)
        self.btn_del.clicked.connect(lambda: self.delete_req.emit(self))
        head.addWidget(self.btn_del)
        lay.addLayout(head)
        lay.addWidget(self.canvas)

    def _add(self, head: QHBoxLayout, key: str, icon: str, tip: str, fn, checkable: bool = False) -> FlatIconButton:
        b = FlatIconButton(icon, tip, 30)
        b.setCheckable(checkable)
        b.clicked.connect(fn)
        head.addWidget(b)
        self.tool_btns[key] = b
        return b

    def _ink_tools(self, head: QHBoxLayout) -> None:
        c: InkCanvas = self.canvas           # type: ignore[assignment]
        self._tool_group = ("pen", "marker", "eraser")
        for key, icon, tip in (("pen", "pen", "قلم"), ("marker", "marker", "ماژیک هایلایت"), ("eraser", "eraser", "پاک‌کن")):
            self._add(head, key, icon, tip, lambda _=False, k=key: self._pick_tool(k), True)
        self.tool_btns["pen"].setChecked(True)
        head.addSpacing(6)
        self.dots: dict[str, ColorDot] = {}
        for key in INK_COLORS:
            d = ColorDot(lambda pal, k=key: ink_color(k, pal).name(), INK_NAMES[key], 20)
            d.clicked.connect(lambda _=False, k=key: self._pick_color(k))
            head.addWidget(d)
            self.dots[key] = d
        self.dots["text"].setChecked(True)
        head.addSpacing(6)
        self.w_btn = self._add(head, "width", "marker", "ضخامت خط: نازک / متوسط / ضخیم", self._cycle_width)
        self.w_btn.setVisible(False)
        self._widths = (1.6, 2.6, 4.6)
        self._wi = 1
        head.addSpacing(6)
        self._add(head, "undo", "undo", "برگرداندن  Ctrl+Z", c.undo)
        self._add(head, "redo", "redo", "از نو", c.redo)
        self._add(head, "bg", "ink_bg", "زمینه: نقطه‌ای / خط‌دار / شطرنجی / ساده", self._cycle_bg)
        self._add(head, "clear", "close", "پاک کردن همه‌ی نوشته‌ها", c.clear)

    def _pick_tool(self, key: str) -> None:
        self.canvas.set_tool(key)
        for k in self._tool_group:
            self.tool_btns[k].setChecked(k == key)

    def _pick_color(self, key: str) -> None:
        self.canvas.set_color(key)
        for k, d in self.dots.items():
            d.setChecked(k == key)
        for k in self._tool_group:
            self.tool_btns[k].setChecked(k == self.canvas.tool)

    def _cycle_width(self) -> None:
        self._wi = (self._wi + 1) % len(self._widths)
        self.canvas.set_width(self._widths[self._wi])

    def _cycle_bg(self) -> None:
        order = ["dots", "lines", "grid", "blank"]
        self.canvas.set_bg(order[(order.index(self.canvas.bg) + 1) % len(order)])

    def _flow_tools(self, head: QHBoxLayout) -> None:
        c: FlowCanvas = self.canvas          # type: ignore[assignment]
        for kind, (lab, icon, _w, _h) in NODE_KINDS.items():
            self._add(head, "add_" + kind, icon, "＋ " + lab, lambda _=False, k=kind: c.add_node(k))
        head.addSpacing(6)
        self._add(head, "tidy", "tidy", "مرتب‌سازی خودکار", c.auto_layout)
        self._add(head, "undo", "undo", "برگرداندن", c.undo)
        self._add(head, "redo", "redo", "از نو", c.redo)

    def data(self) -> dict:
        d = self.canvas.data()
        d["id"] = self.block_id
        return d

    def paintEvent(self, e) -> None:  # noqa: N802
        pal = _fpal(self)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(pal["line"]), 1))
        p.setBrush(alpha(pal["panel"], 1.0))
        p.drawRoundedRect(r, rr(14), rr(14))
        hl = QColor(255, 255, 255, 20)
        p.setPen(QPen(hl, 1))
        p.drawLine(QPointF(r.left() + 16, r.top() + 1), QPointF(r.right() - 16, r.top() + 1))
        super().paintEvent(e)
