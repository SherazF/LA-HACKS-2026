import asyncio
import unittest
import numpy as np
from unittest.mock import MagicMock, AsyncMock
from bus import EventBus
from gemma import ModelManager

class TestPriority(unittest.IsolatedAsyncioTestCase):
    async def test_priority_processing(self):
        bus = EventBus()
        # Mocking query_model to take some time
        model_manager = ModelManager(bus)
        processed_order = []

        async def mock_query_model(prompt, images=None):
            await asyncio.sleep(0.1)
            processed_order.append(prompt)
            return "mock response"

        model_manager._query_model = mock_query_model

        # Put a snapshot in the queue
        mock_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        await bus.emit("snapshot_ready", frame=mock_frame)
        # Put a chat in the queue (should jump ahead if not already processing)
        await bus.emit("chat_input", text="chat1")

        # Start processing for a short time
        task = asyncio.create_task(model_manager.start())
        # Wait more than enough time for 2 items (each takes 0.1s sleep)
        await asyncio.sleep(1.0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        print(f"Processed order: {processed_order}")
        self.assertGreaterEqual(len(processed_order), 2, f"Expected 2 items processed, got {len(processed_order)}")
        self.assertEqual(processed_order[0], "chat1")
        self.assertIn("Analyze this image", processed_order[1])

if __name__ == "__main__":
    unittest.main()
