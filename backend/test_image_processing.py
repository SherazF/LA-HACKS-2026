import base64
import unittest

import cv2
import numpy as np

from bus import EventBus
from model.gemma import IMAGE_RESOLUTION, ModelManager


class TestImageProcessing(unittest.TestCase):
    def test_resize_preserves_aspect_and_no_sharpening(self):
        bus = EventBus()
        manager = ModelManager(bus)

        # 1920x1080 source — should be downsized to fit IMAGE_RESOLUTION while
        # keeping 16:9 aspect.
        src = np.zeros((1080, 1920, 3), dtype=np.uint8)
        cv2.rectangle(src, (200, 200), (400, 400), (255, 255, 255), -1)

        manager._add_frame_to_context(src)

        self.assertEqual(len(manager.context.image_buffer), 1)

        img_data = base64.b64decode(manager.context.image_buffer[0][0])
        nparr = np.frombuffer(img_data, np.uint8)
        decoded = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        target_w, target_h = IMAGE_RESOLUTION
        self.assertLessEqual(decoded.shape[0], target_h)
        self.assertLessEqual(decoded.shape[1], target_w)

        # 16:9 aspect ratio must be preserved (within rounding).
        aspect = decoded.shape[1] / decoded.shape[0]
        self.assertAlmostEqual(aspect, 16 / 9, places=1)

        # Pure-black region of the source must remain (near-)black after our
        # pipeline. Aggressive sharpening would inject ringing halos here.
        flat_region = decoded[10:50, 10:50].mean()
        self.assertLess(flat_region, 5.0, "pipeline should not introduce sharpening artifacts")


if __name__ == "__main__":
    unittest.main()
