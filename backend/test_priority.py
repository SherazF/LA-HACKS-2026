import asyncio
import unittest
from unittest.mock import AsyncMock

import numpy as np

from bus import EventBus
from model.gemma import ModelManager


class TestPriority(unittest.IsolatedAsyncioTestCase):
    async def test_priority_processing(self):
        bus = EventBus()
        manager = ModelManager(bus)
        manager.context.is_initialized = True
        manager._check_connection = AsyncMock()

        processed: list[tuple[str, str | None]] = []

        async def mock_query_model(transient_prompt: str | None = None):
            await asyncio.sleep(0.05)
            last_user = (
                manager.context.history[-1]["content"]
                if manager.context.history and manager.context.history[-1]["role"] == "user"
                else None
            )
            processed.append((transient_prompt or "<chat>", last_user))
            return {"response": "ok"}

        manager._query_model = mock_query_model

        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        await bus.emit("snapshot_ready", frame=frame)
        await bus.emit("chat_input", text="chat1")

        task = asyncio.create_task(manager.start())
        await asyncio.sleep(0.5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        self.assertEqual(len(processed), 2, f"Expected 2 items processed; got {processed}")
        self.assertEqual(processed[0][0], "<chat>", "chat must run before snapshot (priority 0)")
        self.assertEqual(processed[0][1], "chat1")
        self.assertIn(
            "camera frame",
            processed[1][0].lower(),
            "snapshot prompt must come through as transient",
        )

    async def test_snapshot_does_not_pollute_history(self):
        bus = EventBus()
        manager = ModelManager(bus)
        manager.context.is_initialized = True
        manager._check_connection = AsyncMock()

        async def mock_query_model(transient_prompt=None):
            return {"response": "empty"}

        manager._query_model = mock_query_model

        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        for _ in range(5):
            await bus.emit("snapshot_ready", frame=frame)
            manager._snapshot_queued = False

        task = asyncio.create_task(manager.start())
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        snapshot_prompts_in_history = [
            m for m in manager.context.history if "camera frame" in m["content"].lower()
        ]
        self.assertEqual(
            snapshot_prompts_in_history,
            [],
            "snapshot prompts must never enter persistent history",
        )


if __name__ == "__main__":
    unittest.main()
