import asyncio
import unittest
import numpy as np
from unittest.mock import MagicMock, AsyncMock
from bus import EventBus
from model.gemma import ModelManager

class TestPriority(unittest.IsolatedAsyncioTestCase):
    async def test_priority_processing(self):
        bus = EventBus()
        # Mocking query_model to take some time
        model_manager = ModelManager(bus)
        processed_order = []

        # Initialize context so snapshots aren't dropped
        model_manager.context.is_initialized = True

        async def mock_query_model():
            await asyncio.sleep(0.1)
            # We'll check what's in history to see what was processed
            last_role = model_manager.context.history[-1]["role"]
            content = model_manager.context.history[-1]["content"]
            processed_order.append((last_role, content))
            return {"response": "mock response"}

        model_manager._query_model = mock_query_model
        model_manager._check_connection = AsyncMock() # Skip connection check

        # Put a snapshot in the queue (Priority 1)
        mock_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        await bus.emit("snapshot_ready", frame=mock_frame)
        
        # Put a chat in the queue (Priority 0 - should jump ahead)
        await bus.emit("chat_input", text="chat1")

        # Start processing
        task = asyncio.create_task(model_manager.start())
        # Wait for both to be processed
        await asyncio.sleep(0.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        print(f"Processed order: {processed_order}")
        self.assertEqual(len(processed_order), 2, "Expected 2 items processed")
        # First should be the chat message
        self.assertEqual(processed_order[0][1], "chat1")
        # Second should be the snapshot analysis prompt
        self.assertIn("Analyze the current camera frame", processed_order[1][1])

if __name__ == "__main__":
    unittest.main()
