import unittest

from model.context import MAX_IMAGES, ContextManager


class TestContextPruning(unittest.TestCase):
    def test_image_buffer_strict_cap(self):
        ctx = ContextManager(token_limit=1_000_000)

        for i in range(10):
            ctx.add_image(f"img-{i}")

        self.assertEqual(
            len(ctx.image_buffer),
            MAX_IMAGES,
            "image_buffer must be hard-capped at MAX_IMAGES regardless of token_limit",
        )
        self.assertEqual(ctx.image_buffer[-1][0], "img-9", "newest image should win FIFO eviction")

    def test_history_pruning_keeps_initialization(self):
        ctx = ContextManager(token_limit=600)
        ctx.add_message("user", "hello world " * 5)
        ctx.add_message("assistant", "hi there " * 5)

        for i in range(40):
            ctx.add_message("user", f"msg-{i} " * 30)

        self.assertLessEqual(ctx._get_current_total_tokens(), 600)
        self.assertEqual(ctx.history[0]["content"], "hello world " * 5)

    def test_transient_message_does_not_persist(self):
        ctx = ContextManager()
        ctx.add_message("user", "I'm starting my build")
        before = list(ctx.history)

        payload = ctx.get_messages_payload(
            "system instructions",
            transient_user_message="Analyze the camera frame.",
        )

        self.assertEqual(ctx.history, before, "transient messages must not be added to history")
        self.assertEqual(payload[0]["role"], "system")
        self.assertEqual(payload[-1]["role"], "user")
        self.assertEqual(payload[-1]["content"], "Analyze the camera frame.")

    def test_image_attaches_to_last_user_message(self):
        ctx = ContextManager()
        ctx.add_message("user", "hi")
        ctx.add_message("assistant", "hello")
        ctx.add_image("BASE64IMG")

        payload = ctx.get_messages_payload("sys")
        user_msgs = [m for m in payload if m["role"] == "user"]
        self.assertTrue(any("images" in m for m in user_msgs))
        self.assertEqual(user_msgs[-1]["images"], ["BASE64IMG"])

        payload2 = ctx.get_messages_payload("sys", transient_user_message="snapshot")
        self.assertEqual(payload2[-1]["images"], ["BASE64IMG"])
        self.assertEqual(payload2[-1]["content"], "snapshot")


if __name__ == "__main__":
    unittest.main()
