import asyncio
import logging
import httpx
import base64
import cv2
import os
from typing import Dict, List, Optional
from bus import EventBus
from .context import ContextManager

logger = logging.getLogger(__name__)

class ModelManager:
    def __init__(self, bus: EventBus, ollama_url: str = "http://localhost:11434", model_name: str = "gemma"):
        self.bus = bus
        self.ollama_url = ollama_url.rstrip('/')
        self.model_name = model_name
        self.queue = asyncio.PriorityQueue()
        self.context = ContextManager(image_limit=3)
        self.system_prompt_tpl = """You are an expert PC building assistant with vision capabilities.

        Your job is to guide the user step-by-step using:
        1. The current camera image
        2. The conversation history

        You MUST:
        - Be specific and actionable
        - Point out mistakes clearly
        - Give step-by-step instructions
        - Reference visible components when possible

        Always structure responses like:

        OBSERVATION:
        What you see in the image

        ISSUES:
        What is wrong or risky

        ACTION:
        Clear step-by-step instructions

        Keep responses concise but precise.
        Avoid generic advice."""
        self.processing_lock = asyncio.Lock()
        self.current_task = None
        
        # Load Prompts
        self.prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
        self.initial_request_tpl = self._load_prompt("initial_request.txt")
        
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

    async def on_snapshot_ready(self, frame):
        if not self.context.is_initialized:
            # Don't queue snapshots until we have an initial context from the user
            return
        await self.queue.put((1, {"type": "snapshot", "frame": frame}))

    async def on_chat_input(self, text):
        await self.queue.put((0, {"type": "chat", "text": text}))
        if self.current_task and not self.current_task.done():
            logger.info("Chat preempting in-flight vision task...")
            self.current_task.cancel()

    async def start(self):
        logger.info(f"Model Manager (Modular) started (Model: {self.model_name})")
        await self._check_connection()
        
        while True:
            try:
                priority, item = await self.queue.get()
                
                async with self.processing_lock:
                    if item["type"] == "chat":
                        await self._process_chat(item["text"])
                    elif item["type"] == "snapshot":
                        if not self.queue.empty():
                            next_prio, _ = self.queue._queue[0]
                            if next_prio < priority:
                                logger.info("Skipping snapshot for pending chat")
                                self.queue.task_done()
                                continue
                        
                        self.current_task = asyncio.create_task(self._process_snapshot(item["frame"]))
                        try:
                            await self.current_task
                        except asyncio.CancelledError:
                            logger.info("Vision task cancelled")
                        finally:
                            self.current_task = None
                
                self.queue.task_done()
                await self.bus.emit("inference_done")
            except Exception as e:
                logger.error(f"Model Manager error: {e}")
                await asyncio.sleep(0.1)

    async def _process_chat(self, text: str):
        prompt = text
        if not self.context.is_initialized:
            logger.info("First chat message: Initializing build state")
            prompt = self.initial_request_tpl.format(user_input=text)
            self.context.is_initialized = True
        
        self.context.add_message("user", prompt)
        response = await self._query_model()
        
        if response:
            self.context.update_state_from_text(response)
            self.context.add_message("assistant", response)
            await self.bus.emit("chat_response", text=response)

    async def _process_snapshot(self, frame):
        # Convert frame to base64
        _, buffer = cv2.imencode('.jpg', frame)
        img_str = base64.b64encode(buffer).decode('utf-8')
        self.context.add_image(img_str)
        
        prompt = """
        You are analyzing a live video feed of a PC being built.

        Your job is to detect meaningful changes or issues between frames.

        IMPORTANT:
        If there is NO new information, NO new mistakes, and NO actionable guidance compared to previous context, you MUST respond with exactly:

        empty

        (no extra text, no punctuation)

        Only respond with a full answer if:
        - A new component appears
        - A component changes position
        - A mistake is detected
        - The user needs to take action

        If responding, use this format:

        OBSERVATION:
        What changed or what is currently visible

        ISSUES:
        What is wrong or risky (if any)

        ACTION:
        Clear step-by-step instructions

        Be concise and only respond when necessary.
        """
        self.context.add_message("user", prompt)
        
        response = await self._query_model()
        
        if response:
            self.context.update_state_from_text(response)
            self.context.add_message("assistant", response)
            await self.bus.emit("vision_result", text=response)

    async def _query_model(self) -> Optional[str]:
        formatted_state = self.context.get_formatted_state()
        system_prompt = self.system_prompt_tpl.format(
            milestones=formatted_state["milestones"],
            parts=formatted_state["parts"]
        )
        messages = self.context.get_messages_payload(system_prompt)
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{self.ollama_url}/api/chat", json=payload)
                response.raise_for_status()
                result = response.json()
                return result.get("message", {}).get("content", "")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error querying model: {e}")
            return None
