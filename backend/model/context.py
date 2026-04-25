import json
import re
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
            "parts": []
        }
        self.is_initialized: bool = False

    def add_image(self, b64_image: str):
        self.image_buffer.append(b64_image)

    def add_message(self, role: str, content: str):
        self.history.append({"role": role, "content": content})
        if len(self.history) > 10:
            self.history = self.history[-10:]

    def get_messages_payload(self, system_prompt: str) -> List[Dict]:
        messages = [{"role": "system", "content": system_prompt}]
        history_copy = [m.copy() for m in self.history]
        
        if self.image_buffer:
            for msg in reversed(history_copy):
                if msg["role"] == "user":
                    msg["images"] = list(self.image_buffer)
                    break
        
        messages.extend(history_copy)
        return messages

    def update_state_from_text(self, text: str) -> bool:
        match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                updated = False
                if isinstance(data, dict):
                    if "milestones" in data:
                        self.state["milestones"] = data["milestones"]
                        updated = True
                    elif "steps" in data: # Backward compatibility/model confusion
                        self.state["milestones"] = data["steps"]
                        updated = True
                        
                    if "parts" in data:
                        self.state["parts"] = data["parts"]
                        updated = True
                
                if updated:
                    logger.info(f"Context state updated: {self.state}")
                return updated
            except json.JSONDecodeError:
                logger.warning("Failed to parse JSON state block")
        return False

    def get_formatted_state(self) -> Dict[str, str]:
        return {
            "milestones": json.dumps(self.state["milestones"]) if self.state["milestones"] else "None yet",
            "parts": json.dumps(self.state["parts"]) if self.state["parts"] else "None yet"
        }
