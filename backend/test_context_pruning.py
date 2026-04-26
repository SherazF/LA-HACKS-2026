import unittest
from model.context import ContextManager

class TestContextPruning(unittest.TestCase):
    def test_dynamic_pruning(self):
        # Set a limit that can hold 2 images (2048) + init (50) + some buffer
        ctx = ContextManager(token_limit=3000)
        
        # 1. Add initialization messages (~50 tokens total)
        ctx.add_message("user", "Hello" * 20) # 100 chars -> 25 tokens
        ctx.add_message("assistant", "Hi" * 20) # 40 chars -> 10 tokens
        
        # 2. Add an image (1024 tokens for 256x256)
        ctx.add_image("fake_base64_data", resolution=(256, 256))
        
        current_tokens = ctx._get_current_total_tokens()
        self.assertLessEqual(current_tokens, 3000)
        self.assertEqual(len(ctx.image_buffer), 1)
        self.assertEqual(len(ctx.history), 2)
        
        # 3. Add more images - should respect the limit set in ContextManager
        ctx.add_image("second_fake_image", resolution=(256, 256))
        ctx.add_image("third_fake_image", resolution=(256, 256))
        
        # Currently the limit is 1 image
        self.assertEqual(len(ctx.image_buffer), 1)
        self.assertLessEqual(ctx._get_current_total_tokens(), 3000)
        
        # 4. Add many messages to force message pruning
        # Each message is 400 chars -> 100 tokens
        for i in range(10):
            ctx.add_message("user", "word" * 100)
            
        # The first 2 messages should be preserved if possible, but the limit is tight
        # 1024 (image) + 100 (new msg) + 35 (init) = 1159. 
        # Adding more will eventually prune everything except the latest and init.
        
        final_tokens = ctx._get_current_total_tokens()
        self.assertLessEqual(final_tokens, 3000)
        # Initialization messages (first 2) should be there
        self.assertEqual(ctx.history[0]["content"], "Hello" * 20)
        
        print(f"Final context size: {final_tokens} tokens, {len(ctx.history)} messages, {len(ctx.image_buffer)} images")

if __name__ == "__main__":
    unittest.main()
