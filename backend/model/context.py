import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Hard cap on simultaneous images sent to the model. Sending more than 1 image
# tends to confuse smaller vision models (they "hallucinate" objects from older
# frames into the current scene). Keep this at 1 unless you have a strong
# reason to compare frames side-by-side.
MAX_IMAGES = 1

# Per-image token estimate used only for context-budget bookkeeping.
# Gemma 3/4 vision tokenizes a frame to ~256-1024 tokens regardless of pixel
# size, so the old per-pixel heuristic was wildly off. 1024 is a safe upper
# bound that still leaves plenty of room for chat history.
IMAGE_TOKEN_ESTIMATE = 1024


class ContextManager:
    """Persistent chat history + bounded image buffer for the vision model.

    Persistent vs. transient:
    - `history` only contains messages the *user* and *assistant* exchanged in
      conversation. Snapshot/internal analysis prompts are NOT stored here so
      the model isn't distracted by long monologues with itself.
    - `image_buffer` holds at most `MAX_IMAGES` recent frames. New frames evict
      old ones immediately (FIFO).
    - `transient_user_message` (passed to `get_messages_payload`) is appended
      ONCE at query time to direct the model on this specific turn (e.g. a
      snapshot analysis instruction) without being recorded.
    """

    def __init__(self, token_limit: int = 32000):
        self.history: List[Dict] = []
        self.image_buffer: List[tuple] = []  # (b64_data, token_estimate)
        self.token_limit = token_limit
        self.state: Dict = {
            "milestones": [],
            "parts": {},
            "current_objectives": [],
        }
        self.is_initialized: bool = False

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // 4

    def _get_current_total_tokens(self) -> int:
        history_tokens = sum(self._estimate_tokens(m["content"]) for m in self.history)
        image_tokens = sum(img[1] for img in self.image_buffer)
        return history_tokens + image_tokens

    def _enforce_image_cap(self) -> None:
        while len(self.image_buffer) > MAX_IMAGES:
            self.image_buffer.pop(0)

    def _prune_history(self) -> None:
        """Trim oldest messages (after the initialization pair) until under budget."""
        while len(self.history) > 3 and self._get_current_total_tokens() > self.token_limit:
            popped = self.history.pop(2)
            logger.debug("Pruned message from context: %s", popped["role"])
        while self.history and self._get_current_total_tokens() > self.token_limit:
            self.history.pop(0)

    def add_image(self, b64_image: str) -> None:
        self.image_buffer.append((b64_image, IMAGE_TOKEN_ESTIMATE))
        self._enforce_image_cap()
        self._prune_history()

    def add_message(self, role: str, content: str) -> bool:
        if not content or not content.strip() or content.strip().lower() == "empty":
            return False
        if self.history:
            last_msg = self.history[-1]
            if last_msg["role"] == role and last_msg["content"].strip() == content.strip():
                logger.debug("Ignoring duplicate %s message", role)
                return False
        self.history.append({"role": role, "content": content})
        self._prune_history()
        return True

    def get_messages_payload(
        self,
        system_prompt: str,
        transient_user_message: Optional[str] = None,
    ) -> List[Dict]:
        """Build the Ollama /api/chat messages array.

        The current image (if any) is attached to the LAST user message in the
        composed payload. When `transient_user_message` is provided, it is
        appended (and gets the image) without modifying persistent history.
        """
        messages: List[Dict] = [{"role": "system", "content": system_prompt}]
        history_copy = [m.copy() for m in self.history]

        if transient_user_message is not None:
            history_copy.append({"role": "user", "content": transient_user_message})

        if self.image_buffer:
            for msg in reversed(history_copy):
                if msg["role"] == "user":
                    msg["images"] = [img[0] for img in self.image_buffer]
                    break

        messages.extend(history_copy)
        return messages

    def update_state(self, data: Dict) -> bool:
        updated = False
        if isinstance(data.get("milestones"), list):
            self.state["milestones"] = data["milestones"]
            updated = True
        if isinstance(data.get("parts"), dict):
            self.state["parts"] = data["parts"]
            updated = True
        if isinstance(data.get("current_objectives"), list):
            self.state["current_objectives"] = data["current_objectives"]
            updated = True

        if updated:
            logger.info("Context state updated: %s", self.state)
        return updated

    def get_formatted_state(self) -> Dict[str, str]:
        return {
            "milestones": json.dumps(self.state["milestones"]),
            "parts": json.dumps(self.state["parts"]),
            "current_objectives": json.dumps(self.state["current_objectives"]),
        }
