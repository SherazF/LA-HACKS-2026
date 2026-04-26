import json
import logging
from collections import deque
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class ContextManager:
    def __init__(self, token_limit: int = 256000):
        self.history: List[Dict] = []
        self.image_buffer: List[tuple] = [] # Stores (b64_data, token_count)
        self.token_limit = token_limit
        self.state: Dict = {
            "milestones": [],
            "parts": {},
            "current_objectives": []
        }
        self.is_initialized: bool = False

    def _estimate_tokens(self, text: str) -> int:
        """Rough heuristic: 4 characters per token."""
        return len(text) // 4

    def _get_current_total_tokens(self) -> int:
        history_tokens = sum(self._estimate_tokens(m["content"]) for m in self.history)
        image_tokens = sum(img[1] for img in self.image_buffer)
        return history_tokens + image_tokens

    def _prune_context(self):
        """Dynamically prune history and images to stay within token_limit."""
        total = self._get_current_total_tokens()
        if total <= self.token_limit:
            return

        logger.info(f"Pruning context: current tokens {total} exceeds limit {self.token_limit}")

        # Strategy:
        # 1. Strictly limit to 2 images max
        while len(self.image_buffer) > 2:
            self.image_buffer.pop(0)
            logger.debug("Pruned image to maintain strict 2-image limit")

        # 2. Prune further if still over token limit (except the most recent one)
        while len(self.image_buffer) > 1 and self._get_current_total_tokens() > self.token_limit:
            self.image_buffer.pop(0)
            logger.debug("Pruned an image to stay within token budget")

        # 2. Prune history (keep first 2 messages if they exist - initialization)
        while len(self.history) > 3 and self._get_current_total_tokens() > self.token_limit:
            # Pop the message after the initialization pair
            popped = self.history.pop(2)
            logger.debug(f"Pruned a message from context: {popped['role']}")

        # 3. Last resort: Prune even the initialization if still over (unlikely)
        while len(self.history) > 0 and self._get_current_total_tokens() > self.token_limit:
            self.history.pop(0)

    def add_image(self, b64_image: str, resolution: tuple = (256, 256)):
        """Adds an image and estimates tokens based on pixels."""
        # Heuristic: 256x256 image is approx 1024 tokens.
        # Ratio is ~0.0156 tokens per pixel.
        tokens = int(resolution[0] * resolution[1] * 0.015625)
        self.image_buffer.append((b64_image, tokens))
        self._prune_context()

    def add_message(self, role: str, content: str) -> bool:
        if not content or not content.strip() or content.strip().lower() == "empty":
            return False
            
        # Deduplication: Don't add if it's the same as the last message from this role
        if self.history:
            last_msg = self.history[-1]
            if last_msg["role"] == role and last_msg["content"].strip() == content.strip():
                logger.debug(f"Ignoring duplicate message from {role}")
                return False

        self.history.append({"role": role, "content": content})
        self._prune_context()
        return True

    def get_messages_payload(self, system_prompt: str) -> List[Dict]:
        """Constructs the payload for Ollama including images on the latest user message."""
        messages = [{"role": "system", "content": system_prompt}]
        history_copy = [m.copy() for m in self.history]
        
        # Attach images to the last user message if we have them
        if self.image_buffer:
            for msg in reversed(history_copy):
                if msg["role"] == "user":
                    msg["images"] = [img[0] for img in self.image_buffer]
                    break
        
        messages.extend(history_copy)
        return messages

    def update_state(self, data: Dict) -> bool:
        """Updates internal state from structured data dictionary."""
        updated = False
        if "milestones" in data:
            self.state["milestones"] = data["milestones"]
            updated = True
        if "parts" in data:
            self.state["parts"] = data["parts"]
            updated = True
        if "current_objectives" in data:
            self.state["current_objectives"] = data["current_objectives"]
            updated = True
        
        if updated:
            logger.info(f"Context state updated: {self.state}")
        return updated

    def get_formatted_state(self) -> Dict[str, str]:
        """Returns string representations of milestones, parts, and objectives for prompt injection."""
        return {
            "milestones": json.dumps(self.state["milestones"]),
            "parts": json.dumps(self.state["parts"]),
            "current_objectives": json.dumps(self.state["current_objectives"])
        }
