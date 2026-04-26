"""
Thread-safe overlay list for model-driven camera annotations (circles, arrows, clear).
See docs/ollama-camera-overlay-tools.md.
"""
from __future__ import annotations

import re
import threading
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

DEFAULT_BGR = (0, 255, 0)
_MAX_RADIUS = 0.5
_THICKNESS_MIN = 1
_THICKNESS_MAX = 16


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
    return out
