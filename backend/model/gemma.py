import asyncio
import logging
import httpx
import base64
import cv2
import os
import json
import re
from typing import Any, Dict, List, Optional

from bus import EventBus
from overlay_state import OverlayState

from .context import ContextManager

logger = logging.getLogger(__name__)

# Image processing configuration
IMAGE_RESOLUTION = (1280, 720) 

class ModelManager:
    def __init__(
        self,
        bus: EventBus,
        ollama_url: str = "http://localhost:11434",
        model_name: str = "gemma",
        overlay_state: Optional[OverlayState] = None,
    ):
        self.bus = bus
        self.ollama_url = ollama_url.rstrip("/")
        self.model_name = model_name
        self.overlay_state = overlay_state
        self.queue = asyncio.PriorityQueue()
        self.context = ContextManager(token_limit=256000)
        self.processing_lock = asyncio.Lock()
        self.current_task = None
        self._snapshot_queued = False # Track if a snapshot is already waiting
        
        # Load Prompts
        self.prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
        self.system_prompt_tpl = self._load_prompt("system_prompt.txt")
        self.snapshot_prompt_tpl = self._load_prompt("snapshot_prompt.txt")
        self.initial_request_tpl = self._load_prompt("initial_request.txt")
        self.known_parts = self._load_prompt("known_parts.txt")
        
        # Subscribe to events
        self.bus.subscribe("snapshot_ready", self.on_snapshot_ready)
        self.bus.subscribe("chat_input", self.on_chat_input)

    def _load_prompt(self, filename: str) -> str:
        path = os.path.join(self.prompt_dir, filename)
        try:
            with open(path, 'r') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load prompt {filename}: {e}")
            return ""

    async def _check_connection(self):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.ollama_url}/api/tags")
                if response.status_code == 200:
                    models = [m['name'] for m in response.json().get('models', [])]
                    logger.info(f"Connected to Ollama. Models available: {models}")
                else:
                    logger.error(f"Ollama server returned status {response.status_code}")
        except Exception as e:
            logger.error(f"Could not connect to Ollama at {self.ollama_url}: {e}")

    def _add_frame_to_context(self, frame):
        """Helper to encode frame and add to visual memory."""
        if frame is None:
            return

        # Resize to configured resolution to save context space
        frame = cv2.resize(frame, IMAGE_RESOLUTION, interpolation=cv2.INTER_AREA)

        # Apply sharpening using Unsharp Masking (pure OpenCV approach)
        # This enhances edges which helps the model identify components in smaller images
        blurred = cv2.GaussianBlur(frame, (0, 0), 3)
        frame = cv2.addWeighted(frame, 1.5, blurred, -0.5, 0)

        _, buffer = cv2.imencode(".jpg", frame)
        img_str = base64.b64encode(buffer).decode("utf-8")
        self.context.add_image(img_str, resolution=IMAGE_RESOLUTION)
        logger.debug(f"Visual memory updated with processed frame {IMAGE_RESOLUTION}")

    def _apply_overlays_from_response(self, data: Optional[Dict[str, Any]]) -> None:
        if not self.overlay_state or not data:
            return
        ops = data.get("overlay_operations")
        if isinstance(ops, list):
            self.overlay_state.apply_model_operations(ops)

    async def on_snapshot_ready(self, frame):
        if not self.context.is_initialized:
            return
            
        if self._snapshot_queued:
            logger.debug("Snapshot already in queue, dropping new one to prevent backlog")
            return
            
        self._snapshot_queued = True
        await self.queue.put((1, {"type": "snapshot", "frame": frame}))

    async def on_chat_input(self, text, frame=None):
        if frame is not None:
            self._add_frame_to_context(frame)

        # Reset the snapshot timer so we don't double-trigger analysis
        await self.bus.emit("reset_snapshot_timer")

        await self.queue.put((0, {"type": "chat", "text": text}))
        if self.current_task and not self.current_task.done():
            logger.info("Chat preempting in-flight vision task...")
            self.current_task.cancel()

    async def start(self):
        logger.info(f"Model Manager (Structured) started (Model: {self.model_name})")
        await self._check_connection()
        
        while True:
            try:
                priority, item = await self.queue.get()
                
                try:
                    async with self.processing_lock:
                        if item["type"] == "chat":
                            await self._process_chat(item["text"])
                        elif item["type"] == "snapshot":
                            self._snapshot_queued = False # Reset flag since we are now processing it
                            if not self.queue.empty():
                                next_prio, _ = self.queue._queue[0]
                                if next_prio < priority:
                                    logger.info("Skipping snapshot for pending chat")
                                    continue
                            
                            self.current_task = asyncio.create_task(self._process_snapshot(item["frame"]))
                            try:
                                await self.current_task
                            except asyncio.CancelledError:
                                logger.info("Vision task cancelled")
                            finally:
                                self.current_task = None
                finally:
                    self.queue.task_done()
                    # Signal inference done inside the lock to ensure strict timing
                    await self.bus.emit("inference_done")
            except Exception as e:
                logger.error(f"Model Manager error ({type(e).__name__}): {e}", exc_info=True)
                await asyncio.sleep(0.1)

    async def _process_chat(self, text: str):
        prompt = text
        if not self.context.is_initialized:
            logger.info("First chat message: Initializing build state")
            prompt = self.initial_request_tpl.format(user_input=text)
            self.context.is_initialized = True
        
        self.context.add_message("user", prompt)
        json_resp = await self._query_model()
        
        if json_resp:
            self.context.update_state(json_resp)
            self._apply_overlays_from_response(json_resp)
            response_text = json_resp.get("response", "")
            if response_text and response_text.strip().lower() != "empty":
                if self.context.add_message("assistant", response_text):
                    await self.bus.emit("chat_response", text=response_text)

    async def _process_snapshot(self, frame):
        self._add_frame_to_context(frame)
        prompt = self.snapshot_prompt_tpl
        self.context.add_message("user", prompt)
        
        json_resp = await self._query_model()
        
        if json_resp:
            self.context.update_state(json_resp)
            self._apply_overlays_from_response(json_resp)
            response_text = json_resp.get("response", "")
            if response_text and response_text.strip().lower() != "empty":
                if self.context.add_message("assistant", response_text):
                    await self.bus.emit("vision_result", text=response_text)

    async def _query_model(self) -> Optional[Dict]:
        formatted_state = self.context.get_formatted_state()
        try:
            system_prompt = self.system_prompt_tpl.format(
                known_parts=self.known_parts,
                milestones=formatted_state["milestones"],
                parts=formatted_state["parts"],
                current_objectives=formatted_state["current_objectives"],
            )
        except KeyError as e:
            logger.error(f"KeyError in system_prompt.format: {e}")
            logger.error(f"Available keys in system_prompt_tpl: {re.findall(r'\{([^}]+)\}', self.system_prompt_tpl)}")
            raise
        except Exception as e:
            logger.error(f"Error in system_prompt.format: {e}")
            raise
        messages = self.context.get_messages_payload(system_prompt)

        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "format": "json",
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(f"{self.ollama_url}/api/chat", json=payload)
                    response.raise_for_status()
                    result = response.json()
                    content = result.get("message", {}).get("content", "")
                    try:
                        parsed = json.loads(content)
                        logger.info(f"Full model response: {json.dumps(parsed, indent=2)}")
                        return parsed
                    except json.JSONDecodeError:
                        logger.warning(
                            f"Attempt {attempt + 1}: Failed to parse JSON content: {content}"
                        )
                        if attempt == max_retries - 1:
                            return None
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 500:
                    logger.warning(f"Attempt {attempt + 1}: Server returned 500 error")
                    if attempt == max_retries - 1:
                        return None
                else:
                    logger.error(f"HTTP error occurred: {e}")
                    return None
            except (httpx.RequestError, asyncio.TimeoutError) as e:
                logger.warning(f"Attempt {attempt + 1}: Request failed: {e}")
                if attempt == max_retries - 1:
                    return None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Unexpected error querying model: {e}")
                return None

            if attempt < max_retries - 1:
                await asyncio.sleep(1.0) # Wait before retrying

        return None
