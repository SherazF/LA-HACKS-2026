import json
import logging
from collections import deque
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class ContextManager:
    def __init__(self, image_limit: int = 3):
        self.history: List[Dict] = []
        self.image_buffer: deque = deque(maxlen=image_limit)
        self.state: Dict = {
            "milestones": [],
            "parts": {},
            "current_objectives": []
        }
        self.is_initialized: bool = False

    def add_image(self, b64_image: str):
        self.image_buffer.append(b64_image)

    def add_message(self, role: str, content: str):
        if not content or not content.strip() or content.strip().lower() == "empty":
            return
            
        # Deduplication: Don't add if it's the same as the last message from this role
        if self.history:
            last_msg = self.history[-1]
            if last_msg["role"] == role and last_msg["content"].strip() == content.strip():
                logger.debug(f"Ignoring duplicate message from {role}")
                return

        self.history.append({"role": role, "content": content})
        
        # Keep the first 2 messages (initialization) and the last 10 messages
        if len(self.history) > 12:
            initialization = self.history[:2]
            recent_history = self.history[-10:]
            self.history = initialization + recent_history

    def get_messages_payload(self, system_prompt: str) -> List[Dict]:
        """Constructs the payload for Ollama including images on the latest user message."""
        messages = [{"role": "system", "content": system_prompt}]
        history_copy = [m.copy() for m in self.history]
        
        # Attach images to the last user message if we have them
        if self.image_buffer:
            for msg in reversed(history_copy):
                if msg["role"] == "user":
                    msg["images"] = list(self.image_buffer)
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
