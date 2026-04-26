import time
import unittest
from unittest.mock import patch

from overlay_state import OverlayState


class TestOverlayClearing(unittest.TestCase):
    def test_describe_active_empty(self):
        st = OverlayState()
        self.assertEqual(st.describe_active(), "none")

    def test_describe_active_circle_and_arrow(self):
        st = OverlayState()
        st.apply_model_operations(
            [
                {
                    "op": "draw_circle",
                    "id": "cpu",
                    "center_x": 0.5,
                    "center_y": 0.4,
                    "radius": 0.08,
                    "label": "CPU socket",
                },
                {
                    "op": "draw_arrow",
                    "id": "ram_arrow",
                    "from_x": 0.1,
                    "from_y": 0.9,
                    "to_x": 0.5,
                    "to_y": 0.5,
                },
            ]
        )
        desc = st.describe_active()
        self.assertIn("cpu:", desc)
        self.assertIn("circle", desc)
        self.assertIn("CPU socket", desc)
        self.assertIn("ram_arrow:", desc)
        self.assertIn("arrow", desc)

    def test_clear_overlays_op_wipes_all(self):
        st = OverlayState()
        st.apply_model_operations(
            [
                {"op": "draw_circle", "center_x": 0.5, "center_y": 0.5, "radius": 0.05},
                {"op": "draw_arrow", "from_x": 0.1, "from_y": 0.1, "to_x": 0.2, "to_y": 0.2},
            ]
        )
        self.assertEqual(len(st.snapshot_shapes()), 2)
        st.apply_model_operations([{"op": "clear_overlays"}])
        self.assertEqual(len(st.snapshot_shapes()), 0)
        self.assertEqual(st.describe_active(), "none")

    def test_clear_then_redraw_in_same_turn(self):
        st = OverlayState()
        st.apply_model_operations(
            [
                {"op": "draw_circle", "id": "old", "center_x": 0.2, "center_y": 0.2, "radius": 0.05},
            ]
        )
        st.apply_model_operations(
            [
                {"op": "clear_overlays"},
                {"op": "draw_circle", "id": "new", "center_x": 0.7, "center_y": 0.7, "radius": 0.05},
            ]
        )
        shapes = st.snapshot_shapes()
        self.assertEqual(len(shapes), 1)
        self.assertEqual(shapes[0]["id"], "new")

    def test_clear_stale_drops_old_overlays(self):
        st = OverlayState()
        fake_now = [1000.0]

        def fake_monotonic():
            return fake_now[0]

        with patch("overlay_state.time.monotonic", fake_monotonic):
            st.apply_model_operations(
                [{"op": "draw_circle", "id": "stale", "center_x": 0.5, "center_y": 0.5, "radius": 0.05}]
            )
            fake_now[0] = 1100.0  # 100s later
            st.apply_model_operations(
                [{"op": "draw_circle", "id": "fresh", "center_x": 0.6, "center_y": 0.6, "radius": 0.05}]
            )
            cleared = st.clear_stale(max_age_seconds=45.0)
        self.assertEqual(cleared, 1)
        ids = [s["id"] for s in st.snapshot_shapes()]
        self.assertEqual(ids, ["fresh"])

    def test_clear_stale_keeps_recent(self):
        st = OverlayState()
        st.apply_model_operations(
            [{"op": "draw_circle", "center_x": 0.5, "center_y": 0.5, "radius": 0.05}]
        )
        cleared = st.clear_stale(max_age_seconds=60.0)
        self.assertEqual(cleared, 0)
        self.assertEqual(len(st.snapshot_shapes()), 1)

    def test_redrawing_same_id_refreshes_age(self):
        st = OverlayState()
        fake_now = [1000.0]

        def fake_monotonic():
            return fake_now[0]

        with patch("overlay_state.time.monotonic", fake_monotonic):
            st.apply_model_operations(
                [{"op": "draw_circle", "id": "cpu", "center_x": 0.5, "center_y": 0.5, "radius": 0.05}]
            )
            fake_now[0] = 1100.0
            st.apply_model_operations(
                [{"op": "draw_circle", "id": "cpu", "center_x": 0.55, "center_y": 0.55, "radius": 0.05}]
            )
            cleared = st.clear_stale(max_age_seconds=45.0)
        self.assertEqual(cleared, 0)
        shapes = st.snapshot_shapes()
        self.assertEqual(len(shapes), 1)
        self.assertAlmostEqual(shapes[0]["center_x"], 0.55)


if __name__ == "__main__":
    unittest.main()
