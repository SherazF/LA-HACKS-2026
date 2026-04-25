import asyncio
import unittest
from bus import EventBus

class TestEventBus(unittest.IsolatedAsyncioTestCase):
    async def test_emit_receive(self):
        bus = EventBus()
        received_data = {}

        async def handler(**kwargs):
            received_data.update(kwargs)

        bus.subscribe("test_event", handler)
        await bus.emit("test_event", key="value")
        
        self.assertEqual(received_data["key"], "value")

    async def test_multiple_handlers(self):
        bus = EventBus()
        count = 0

        async def h1(**kwargs):
            nonlocal count
            count += 1

        async def h2(**kwargs):
            nonlocal count
            count += 1

        bus.subscribe("inc", h1)
        bus.subscribe("inc", h2)
        await bus.emit("inc")
        
        self.assertEqual(count, 2)

if __name__ == "__main__":
    unittest.main()
