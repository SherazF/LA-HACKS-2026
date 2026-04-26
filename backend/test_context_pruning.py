import unittest
from model.context import ContextManager

class TestContextPruning(unittest.TestCase):
    def test_dynamic_pruning(self):
        # Set a small limit for testing: 1000 tokens
        # 1 image = 1024 tokens, so adding 1 image should trigger pruning if we add anything else
        ctx = ContextManager(token_limit=1500)
        
        # 1. Add initialization messages (~50 tokens total)
        ctx.add_message("user", "Hello" * 20) # 100 chars -> 25 tokens
        ctx.add_message("assistant", "Hi" * 20) # 40 chars -> 10 tokens
        
        # 2. Add an image (1024 tokens for 256x256)
        ctx.add_image("fake_base64_data", resolution=(256, 256))
        
        current_tokens = ctx._get_current_total_tokens()
        self.assertLessEqual(current_tokens, 1500)
        self.assertEqual(len(ctx.image_buffer), 1)
        self.assertEqual(len(ctx.history), 2)
        
        # 3. Add another image - should prune the first one
        ctx.add_image("second_fake_image", resolution=(256, 256))
        self.assertEqual(len(ctx.image_buffer), 1)
        self.assertLessEqual(ctx._get_current_total_tokens(), 1500)
        
        # 4. Add many messages to force message pruning
        # Each message is 400 chars -> 100 tokens
        for i in range(10):
            ctx.add_message("user", "word" * 100)
            
        # The first 2 messages should be preserved if possible, but the limit is tight
        # 1024 (image) + 100 (new msg) + 35 (init) = 1159. 
        # Adding more will eventually prune everything except the latest and init.
        
        final_tokens = ctx._get_current_total_tokens()
        self.assertLessEqual(final_tokens, 1500)
        # Initialization messages (first 2) should be there
        self.assertEqual(ctx.history[0]["content"], "Hello" * 20)
        
        print(f"Final context size: {final_tokens} tokens, {len(ctx.history)} messages, {len(ctx.image_buffer)} images")

if __name__ == "__main__":
    unittest.main()
