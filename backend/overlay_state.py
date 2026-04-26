"""
Thread-safe overlay list for model-driven camera annotations (circles, arrows, clear).
See docs/ollama-camera-overlay-tools.md.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

DEFAULT_BGR = (0, 255, 0)
_MAX_RADIUS = 0.5
_THICKNESS_MIN = 1
_THICKNESS_MAX = 16

# Overlays older than this are auto-cleared as a safety net so the model can't
# leave stale annotations sitting on screen forever if it forgets to issue
# a clear_overlays op. The model can refresh an overlay by re-emitting it
# (which resets its created_at timestamp via the same `id`).
DEFAULT_STALE_AGE_SECONDS = 45.0


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _clip_radius(x: float) -> float:
    return max(0.0, min(_MAX_RADIUS, float(x)))


def parse_color(value: Any) -> Tuple[int, int, int]:
    if value is None:
        return DEFAULT_BGR
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            b, g, r = (int(c) for c in value)
            return (max(0, min(255, b)), max(0, min(255, g)), max(0, min(255, r)))
        except (TypeError, ValueError):
            return DEFAULT_BGR
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("#") and len(s) == 7:
            hx = s[1:]
        elif len(s) == 6 and re.match(r"^[0-9a-fA-F]{6}$", s):
            hx = s
        else:
            return DEFAULT_BGR
        r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
        return b, g, r
    return DEFAULT_BGR


class OverlayState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._shapes: List[Dict[str, Any]] = []

    def clear_all(self) -> None:
        with self._lock:
            self._shapes.clear()

    def remove_by_id(self, shape_id: str) -> None:
        with self._lock:
            self._shapes = [s for s in self._shapes if s.get("id") != shape_id]

    def apply_model_operations(self, operations: Optional[List[Dict[str, Any]]]) -> None:
        if not operations:
            return
        for raw in operations:
            op = raw or {}
            kind = (op.get("op") or "").strip().lower()
            if kind == "draw_circle":
                self._add_circle(op)
            elif kind == "draw_arrow":
                self._add_arrow(op)
            elif kind in ("draw_box", "highlight"):
                self._add_box(op)
            elif kind in ("draw_label", "label", "draw_pin", "pin"):
                self._add_label(op)
            elif kind in ("clear_overlays", "clear"):
                cid = op.get("id")
                if cid is not None and str(cid).strip():
                    self.remove_by_id(str(cid).strip())
                else:
                    self.clear_all()
            else:
                continue

    def _add_circle(self, op: Dict[str, Any]) -> None:
        try:
            rec = {
                "type": "circle",
                "id": (str(op["id"]).strip() if op.get("id") is not None else None) or None,
                "center_x": _clip01(op["center_x"]),
                "center_y": _clip01(op["center_y"]),
                "radius": _clip_radius(op.get("radius", 0.05)),
                "label": (str(op["label"]).strip() if op.get("label") is not None else None) or None,
                "color": parse_color(op.get("color")),
                "created_at": time.monotonic(),
            }
        except (KeyError, TypeError, ValueError):
            return
        with self._lock:
            sid = rec.get("id")
            if sid:
                self._shapes = [s for s in self._shapes if s.get("id") != sid]
            self._shapes.append(rec)

    def _add_arrow(self, op: Dict[str, Any]) -> None:
        try:
            th = int(op.get("thickness", 2))
        except (TypeError, ValueError):
            th = 2
        th = max(_THICKNESS_MIN, min(_THICKNESS_MAX, th))
        try:
            rec = {
                "type": "arrow",
                "id": (str(op["id"]).strip() if op.get("id") is not None else None) or None,
                "from_x": _clip01(op["from_x"]),
                "from_y": _clip01(op["from_y"]),
                "to_x": _clip01(op["to_x"]),
                "to_y": _clip01(op["to_y"]),
                "thickness": th,
                "color": parse_color(op.get("color")),
                "created_at": time.monotonic(),
            }
        except (KeyError, TypeError, ValueError):
            return
        with self._lock:
            sid = rec.get("id")
            if sid:
                self._shapes = [s for s in self._shapes if s.get("id") != sid]
            self._shapes.append(rec)

    def _add_box(self, op: Dict[str, Any]) -> None:
        """Axis-aligned highlight rectangle. Accepts either (x0,y0,x1,y1) or
        (x,y,w,h). Auto-normalizes order so x0<x1 and y0<y1."""
        try:
            if "x0" in op or "y0" in op:
                x0 = _clip01(op["x0"]); y0 = _clip01(op["y0"])
                x1 = _clip01(op["x1"]); y1 = _clip01(op["y1"])
            elif "x" in op and "w" in op:
                x = _clip01(op["x"]); y = _clip01(op["y"])
                w = _clip01(op["w"]); h = _clip01(op["h"])
                x0, y0, x1, y1 = x, y, _clip01(x + w), _clip01(y + h)
            else:
                return
            if x1 < x0:
                x0, x1 = x1, x0
            if y1 < y0:
                y0, y1 = y1, y0
            try:
                th = int(op.get("thickness", 3))
            except (TypeError, ValueError):
                th = 3
            th = max(_THICKNESS_MIN, min(_THICKNESS_MAX, th))
            rec = {
                "type": "box",
                "id": (str(op["id"]).strip() if op.get("id") is not None else None) or None,
                "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "thickness": th,
                "label": (str(op["label"]).strip() if op.get("label") is not None else None) or None,
                "color": parse_color(op.get("color")),
                "created_at": time.monotonic(),
            }
        except (KeyError, TypeError, ValueError):
            return
        with self._lock:
            sid = rec.get("id")
            if sid:
                self._shapes = [s for s in self._shapes if s.get("id") != sid]
            self._shapes.append(rec)

    def _add_label(self, op: Dict[str, Any]) -> None:
        """Pin: small filled dot at (x,y) with a text caption."""
        try:
            text = str(op.get("text") or op.get("label") or "").strip()
            if not text:
                return
            rec = {
                "type": "label",
                "id": (str(op["id"]).strip() if op.get("id") is not None else None) or None,
                "x": _clip01(op["x"]),
                "y": _clip01(op["y"]),
                "text": text[:40],
                "color": parse_color(op.get("color")),
                "created_at": time.monotonic(),
            }
        except (KeyError, TypeError, ValueError):
            return
        with self._lock:
            sid = rec.get("id")
            if sid:
                self._shapes = [s for s in self._shapes if s.get("id") != sid]
            self._shapes.append(rec)

    def snapshot_shapes(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(s) for s in self._shapes]

    def clear_stale(self, max_age_seconds: float = DEFAULT_STALE_AGE_SECONDS) -> int:
        """Drop overlays that haven't been refreshed recently. Returns the number cleared."""
        cutoff = time.monotonic() - max_age_seconds
        with self._lock:
            before = len(self._shapes)
            self._shapes = [s for s in self._shapes if s.get("created_at", 0) >= cutoff]
            return before - len(self._shapes)

    def describe_active(self) -> str:
        """Compact human-readable summary of currently-drawn overlays for the model.

        Format keeps tokens low while still letting the model decide whether to
        clear or replace existing shapes. Empty list → "none".
        """
        with self._lock:
            shapes = list(self._shapes)
        if not shapes:
            return "none"
        now = time.monotonic()
        parts: List[str] = []
        for i, s in enumerate(shapes):
            age = max(0, int(now - s.get("created_at", now)))
            sid = s.get("id") or f"#{i + 1}"
            if s.get("type") == "circle":
                label = s.get("label") or "(no label)"
                parts.append(
                    f'{sid}: circle@({s["center_x"]:.2f},{s["center_y"]:.2f}) "{label}" ({age}s old)'
                )
            elif s.get("type") == "arrow":
                parts.append(
                    f'{sid}: arrow ({s["from_x"]:.2f},{s["from_y"]:.2f})→({s["to_x"]:.2f},{s["to_y"]:.2f}) ({age}s old)'
                )
            elif s.get("type") == "box":
                label = s.get("label") or "(no label)"
                parts.append(
                    f'{sid}: box ({s["x0"]:.2f},{s["y0"]:.2f})→({s["x1"]:.2f},{s["y1"]:.2f}) "{label}" ({age}s old)'
                )
            elif s.get("type") == "label":
                parts.append(
                    f'{sid}: label@({s["x"]:.2f},{s["y"]:.2f}) "{s["text"]}" ({age}s old)'
                )
        return "; ".join(parts)


def render_overlays(
    bgr: np.ndarray,
    overlay: Optional[OverlayState],
) -> np.ndarray:
    """Return a BGR image copy with all overlay shapes drawn; if overlay is None, return a copy of bgr."""
    if bgr is None or bgr.size == 0:
        return bgr
    out = bgr.copy()
    if overlay is None:
        return out
    h, w = out.shape[:2]
    if h < 1 or w < 1:
        return out
    shapes = overlay.snapshot_shapes()
    for s in shapes:
        t = s.get("type")
        if t == "circle":
            cx = int(s["center_x"] * w)
            cy = int(s["center_y"] * h)
            r = int(s["radius"] * min(w, h))
            if r < 1:
                r = 1
            color = s.get("color", DEFAULT_BGR)
            cv2.circle(out, (cx, cy), r, color, 2, lineType=cv2.LINE_AA)
            label = s.get("label")
            if label:
                y_text = min(h - 4, cy + r + 18)
                cv2.putText(
                    out,
                    label,
                    (max(0, cx - 60), y_text),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    1,
                    lineType=cv2.LINE_AA,
                )
        elif t == "arrow":
            p0 = (int(s["from_x"] * w), int(s["from_y"] * h))
            p1 = (int(s["to_x"] * w), int(s["to_y"] * h))
            th = int(s.get("thickness", 2))
            color = s.get("color", DEFAULT_BGR)
            cv2.arrowedLine(
                out, p0, p1, color, th, line_type=cv2.LINE_AA, tipLength=0.2,
            )
        elif t == "box":
            x0 = int(s["x0"] * w); y0 = int(s["y0"] * h)
            x1 = int(s["x1"] * w); y1 = int(s["y1"] * h)
            color = s.get("color", DEFAULT_BGR)
            th = int(s.get("thickness", 3))
            tinted = out.copy()
            cv2.rectangle(tinted, (x0, y0), (x1, y1), color, -1)
            cv2.addWeighted(tinted, 0.18, out, 0.82, 0, out)
            cv2.rectangle(out, (x0, y0), (x1, y1), color, th, lineType=cv2.LINE_AA)
            label = s.get("label")
            if label:
                font = cv2.FONT_HERSHEY_SIMPLEX
                scale = 0.55
                thick = 1
                (tw, th_text), _ = cv2.getTextSize(label, font, scale, thick)
                pad = 4
                bx0 = max(0, x0)
                by0 = max(th_text + pad * 2, y0) - (th_text + pad * 2)
                bx1 = min(w - 1, bx0 + tw + pad * 2)
                by1 = by0 + th_text + pad * 2
                cv2.rectangle(out, (bx0, by0), (bx1, by1), color, -1)
                cv2.putText(
                    out, label, (bx0 + pad, by1 - pad),
                    font, scale, (0, 0, 0), thick, lineType=cv2.LINE_AA,
                )
        elif t == "label":
            cx = int(s["x"] * w); cy = int(s["y"] * h)
            color = s.get("color", DEFAULT_BGR)
            text = s.get("text", "")
            cv2.circle(out, (cx, cy), 8, color, -1, lineType=cv2.LINE_AA)
            cv2.circle(out, (cx, cy), 8, (255, 255, 255), 2, lineType=cv2.LINE_AA)
            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = 0.55
            thick = 1
            (tw, th_text), _ = cv2.getTextSize(text, font, scale, thick)
            pad = 4
            tx0 = max(0, cx + 14)
            ty0 = max(th_text + pad * 2, cy + th_text // 2)
            tx1 = min(w - 1, tx0 + tw + pad * 2)
            ty1 = ty0 + pad
            ry0 = ty0 - th_text - pad
            cv2.rectangle(out, (tx0, ry0), (tx1, ty1), color, -1)
            cv2.putText(
                out, text, (tx0 + pad, ty0),
                font, scale, (0, 0, 0), thick, lineType=cv2.LINE_AA,
            )
    return out
