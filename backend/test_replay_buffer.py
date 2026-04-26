"""Replay buffer for chat / vision messages must survive a brief WS disconnect.

Reproduces the bug we hit live: backend emits a chat_response while the
frontend is mid-reconnect (0 active clients) — the message must NOT be
silently dropped, and the next client to connect MUST receive it.
"""
import asyncio
import json
import time
import unittest
from unittest.mock import patch

import ws_bridge
from ws_bridge import ConnectionManager, REPLAY_BUFFER_SIZE, REPLAY_MAX_AGE_SECONDS


class FakeWS:
    def __init__(self):
        self.sent: list[str] = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_text(self, text: str):
        self.sent.append(text)


class TestReplayBuffer(unittest.IsolatedAsyncioTestCase):
    async def test_chat_response_with_no_clients_is_buffered_and_replayed(self):
        mgr = ConnectionManager()
        await mgr.broadcast_json({"v": 1, "type": "chat_response", "text": "first"})
        await mgr.broadcast_json({"v": 1, "type": "chat_response", "text": "second"})

        ws = FakeWS()
        await mgr.connect(ws)

        self.assertTrue(ws.accepted)
        replayed = [json.loads(m) for m in ws.sent]
        replayed_texts = [m.get("text") for m in replayed if m.get("type") == "chat_response"]
        self.assertEqual(replayed_texts, ["first", "second"])

    async def test_vision_result_buffered_too(self):
        mgr = ConnectionManager()
        await mgr.broadcast_json({"v": 1, "type": "vision_result", "text": "snap"})
        ws = FakeWS()
        await mgr.connect(ws)
        types = [json.loads(m).get("type") for m in ws.sent]
        self.assertIn("vision_result", types)

    async def test_voice_state_is_not_replayed(self):
        mgr = ConnectionManager()
        await mgr.broadcast_json(
            {"v": 1, "type": "voice_state", "listening": True, "mode": "auto"}
        )
        ws = FakeWS()
        await mgr.connect(ws)
        # voice_state is transient and must not be in the replay
        types = [json.loads(m).get("type") for m in ws.sent]
        self.assertNotIn("voice_state", types)

    async def test_old_messages_dropped_by_age(self):
        mgr = ConnectionManager()
        with patch.object(ws_bridge.time, "monotonic", return_value=1000.0):
            await mgr.broadcast_json(
                {"v": 1, "type": "chat_response", "text": "old"}
            )
        with patch.object(
            ws_bridge.time,
            "monotonic",
            return_value=1000.0 + REPLAY_MAX_AGE_SECONDS + 1,
        ):
            ws = FakeWS()
            await mgr.connect(ws)
        texts = [
            json.loads(m).get("text")
            for m in ws.sent
            if json.loads(m).get("type") == "chat_response"
        ]
        self.assertEqual(texts, [])

    async def test_buffer_capped_at_size(self):
        mgr = ConnectionManager()
        for i in range(REPLAY_BUFFER_SIZE + 5):
            await mgr.broadcast_json(
                {"v": 1, "type": "chat_response", "text": f"m{i}"}
            )
        ws = FakeWS()
        await mgr.connect(ws)
        chat_msgs = [
            json.loads(m) for m in ws.sent if json.loads(m).get("type") == "chat_response"
        ]
        self.assertEqual(len(chat_msgs), REPLAY_BUFFER_SIZE)
        # Oldest should be dropped
        self.assertEqual(chat_msgs[0]["text"], "m5")
        self.assertEqual(chat_msgs[-1]["text"], f"m{REPLAY_BUFFER_SIZE + 4}")

    async def test_active_clients_still_get_live_broadcast(self):
        mgr = ConnectionManager()
        ws = FakeWS()
        await mgr.connect(ws)
        ws.sent.clear()
        await mgr.broadcast_json({"v": 1, "type": "chat_response", "text": "live"})
        self.assertEqual(json.loads(ws.sent[0]).get("text"), "live")


if __name__ == "__main__":
    unittest.main()
