"""Tests for the new spatial-pointing ops (draw_box, draw_label) and the
coordinate ruler baked into the model-input frame."""
import unittest
from unittest.mock import patch

import numpy as np

from overlay_state import OverlayState, render_overlays
from model import gemma as gemma_mod
from model.gemma import _add_coordinate_ruler, RULER_MARGIN_PX


class TestSpatialOps(unittest.TestCase):
    def test_draw_box_xyxy(self):
        st = OverlayState()
        st.apply_model_operations(
            [
                {
                    "op": "draw_box",
                    "id": "ram",
                    "x0": 0.30,
                    "y0": 0.40,
                    "x1": 0.55,
                    "y1": 0.62,
                    "label": "DIMM",
                    "color": "#ff8a55",
                }
            ]
        )
        shapes = st.snapshot_shapes()
        self.assertEqual(len(shapes), 1)
        s = shapes[0]
        self.assertEqual(s["type"], "box")
        self.assertAlmostEqual(s["x0"], 0.30)
        self.assertAlmostEqual(s["x1"], 0.55)
        self.assertEqual(s["label"], "DIMM")
        self.assertIn("box", st.describe_active())
        self.assertIn("DIMM", st.describe_active())

    def test_draw_box_xywh_normalizes_order(self):
        st = OverlayState()
        st.apply_model_operations(
            [
                {
                    "op": "draw_box",
                    "x": 0.7,
                    "y": 0.6,
                    "w": -0.3,  # backwards-width on purpose
                    "h": 0.2,
                }
            ]
        )
        s = st.snapshot_shapes()[0]
        self.assertLessEqual(s["x0"], s["x1"])
        self.assertLessEqual(s["y0"], s["y1"])

    def test_draw_label_emits_pin_with_text(self):
        st = OverlayState()
        st.apply_model_operations(
            [
                {
                    "op": "draw_label",
                    "x": 0.78,
                    "y": 0.30,
                    "text": "PCIe x16",
                    "id": "pcie",
                }
            ]
        )
        s = st.snapshot_shapes()[0]
        self.assertEqual(s["type"], "label")
        self.assertEqual(s["text"], "PCIe x16")
        self.assertIn("PCIe x16", st.describe_active())

    def test_label_with_empty_text_is_dropped(self):
        st = OverlayState()
        st.apply_model_operations([{"op": "draw_label", "x": 0.5, "y": 0.5, "text": ""}])
        self.assertEqual(len(st.snapshot_shapes()), 0)

    def test_render_box_and_label_do_not_crash(self):
        st = OverlayState()
        st.apply_model_operations(
            [
                {"op": "draw_box", "x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.5, "label": "box"},
                {"op": "draw_label", "x": 0.7, "y": 0.7, "text": "label"},
                {"op": "draw_circle", "center_x": 0.3, "center_y": 0.3, "radius": 0.05},
                {"op": "draw_arrow", "from_x": 0.0, "from_y": 0.0, "to_x": 0.4, "to_y": 0.4},
            ]
        )
        bgr = np.full((300, 400, 3), 50, dtype=np.uint8)
        out = render_overlays(bgr, st)
        self.assertEqual(out.shape, bgr.shape)
        self.assertFalse(np.array_equal(out, bgr), "render_overlays should change pixels")

    def test_box_label_alias_highlight(self):
        st = OverlayState()
        st.apply_model_operations(
            [{"op": "highlight", "x0": 0.1, "y0": 0.1, "x1": 0.2, "y1": 0.2}]
        )
        self.assertEqual(st.snapshot_shapes()[0]["type"], "box")

    def test_label_alias_pin(self):
        st = OverlayState()
        st.apply_model_operations(
            [{"op": "pin", "x": 0.5, "y": 0.5, "text": "here"}]
        )
        self.assertEqual(st.snapshot_shapes()[0]["type"], "label")


class TestCoordinateRuler(unittest.TestCase):
    def test_ruler_adds_margin(self):
        frame = np.full((576, 1024, 3), 100, dtype=np.uint8)
        out = _add_coordinate_ruler(frame)
        self.assertEqual(out.shape[0], 576 + RULER_MARGIN_PX)
        self.assertEqual(out.shape[1], 1024 + RULER_MARGIN_PX)

    def test_ruler_preserves_scene_pixels_when_grid_disabled(self):
        frame = np.random.randint(0, 256, (200, 320, 3), dtype=np.uint8)
        with patch.object(gemma_mod, "RULER_FAINT_GRID_ENABLED", False):
            out = _add_coordinate_ruler(frame)
        scene_region = out[RULER_MARGIN_PX:, RULER_MARGIN_PX:]
        self.assertTrue(
            np.array_equal(scene_region, frame),
            "with faint grid off, scene area must be byte-identical",
        )

    def test_ruler_grid_pollution_is_minimal(self):
        frame = np.full((200, 320, 3), 100, dtype=np.uint8)
        with patch.object(gemma_mod, "RULER_FAINT_GRID_ENABLED", True):
            out = _add_coordinate_ruler(frame)
        scene_region = out[RULER_MARGIN_PX:, RULER_MARGIN_PX:]
        diff_pixels = int(np.any(scene_region != frame, axis=-1).sum())
        total = scene_region.shape[0] * scene_region.shape[1]
        self.assertLess(
            diff_pixels / total,
            0.05,
            f"faint grid changed {diff_pixels}/{total} pixels — too invasive",
        )

    def test_ruler_handles_tiny_frame(self):
        frame = np.full((16, 16, 3), 80, dtype=np.uint8)
        out = _add_coordinate_ruler(frame)
        self.assertEqual(out.shape, (16 + RULER_MARGIN_PX, 16 + RULER_MARGIN_PX, 3))

    def test_ruler_is_noop_on_empty(self):
        out = _add_coordinate_ruler(None)
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
