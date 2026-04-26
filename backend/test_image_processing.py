import unittest
import numpy as np
import cv2
import base64
from unittest.mock import MagicMock
from model.gemma import ModelManager
from bus import EventBus

class TestImageProcessing(unittest.TestCase):
    def test_compression_and_sharpening(self):
        bus = EventBus()
        model_manager = ModelManager(bus)
        
        # Create a 640x480 test frame (standard camera res)
        # Add some patterns to see if sharpening works (though we just check size here)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.rectangle(frame, (100, 100), (200, 200), (255, 255, 255), -1)
        
        # Manually call _add_frame_to_context
        model_manager._add_frame_to_context(frame)
        
        # Check context
        self.assertEqual(len(model_manager.context.image_buffer), 1)
        
        # Decode the image back from base64 (it's now a tuple of (data, tokens))
        img_data = base64.b64decode(model_manager.context.image_buffer[0][0])
        nparr = np.frombuffer(img_data, np.uint8)
        decoded_frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # Verify dimensions are 720p
        self.assertEqual(decoded_frame.shape[0], 720)
        self.assertEqual(decoded_frame.shape[1], 1280)
        
        print(f"Verified image processed: {frame.shape} -> {decoded_frame.shape}")

if __name__ == "__main__":
    unittest.main()
