import asyncio
import logging
import httpx
import json
import base64
import cv2
from typing import Dict, List, Optional
from bus import EventBus

logger = logging.getLogger(__name__)

class ModelManager:
    def __init__(self, bus: EventBus, ollama_url: str = "http://localhost:11434", model_name: str = "gemma"):
        self.bus = bus
        self.ollama_url = ollama_url.rstrip('/')
        self.model_name = model_name
        self.queue = asyncio.PriorityQueue()
        self.chat_history: List[Dict] = []
        self.system_prompt = "You are a PC build guide assistant. Help the user build their PC based on the camera feed and chat."
        self.turn_count = 0
        self.compression_threshold = 10
        self.processing_lock = asyncio.Lock()
        self.current_task = None
        
        # Subscribe to events
        self.bus.subscribe("snapshot_ready", self.on_snapshot_ready)
        self.bus.subscribe("chat_input", self.on_chat_input)

    async def _check_connection(self):
        """Startup diagnostic to list models and verify URL."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.ollama_url}/api/tags")
                if response.status_code == 200:
                    models = [m['name'] for m in response.json().get('models', [])]
                    logger.info(f"Connected to Ollama. Models available: {models}")
                    if self.model_name not in models and f"{self.model_name}:latest" not in models:
                        logger.warning(f"Model '{self.model_name}' not found! App will likely 404. Available: {models}")
                else:
                    logger.error(f"Ollama server at {self.ollama_url} returned status {response.status_code}")
        except Exception as e:
            logger.error(f"Could not connect to Ollama at {self.ollama_url}: {e}")

    async def on_snapshot_ready(self, frame):
        await self.queue.put((1, {"type": "snapshot", "frame": frame}))

    async def on_chat_input(self, text):
        # Priority 0 for chat (preempts snapshots)
        await self.queue.put((0, {"type": "chat", "text": text}))
        # Cancel current task if it's a snapshot/vision task
        if self.current_task and not self.current_task.done():
            logger.info("Chat preempting in-flight vision task...")
            self.current_task.cancel()

    async def start(self):
        logger.info(f"Model Manager started (Model: {self.model_name})")
        await self._check_connection()
        
        while True:
            try:
                priority, item = await self.queue.get()
                
                async with self.processing_lock:
                    if item["type"] == "chat":
                        await self._process_chat(item["text"])
                    elif item["type"] == "snapshot":
                        # Pre-check preemption
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
        self.chat_history.append({"role": "user", "content": text})
        response = await self._query_model(text)
        if response:
            self.chat_history.append({"role": "assistant", "content": response})
            await self.bus.emit("chat_response", text=response)
        self.turn_count += 1
        await self._check_compression()

    async def _process_snapshot(self, frame):
        _, buffer = cv2.imencode('.jpg', frame)
        img_str = base64.b64encode(buffer).decode('utf-8')
        
        prompt = "Analyze this image and provide guidance on the PC build process. What do you see? Are there any errors?"
        response = await self._query_model(prompt, images=[img_str])
        
        if response:
            await self.bus.emit("vision_result", text=response)
        self.turn_count += 1
        await self._check_compression()

    async def _query_model(self, prompt: str, images: Optional[List[str]] = None) -> Optional[str]:
        payload = {
            "model": self.model_name,
            "messages": [{"role": "system", "content": self.system_prompt}] + self.chat_history + [{"role": "user", "content": prompt}],
            "stream": False
        }
        if images:
            payload["messages"][-1]["images"] = images

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(f"{self.ollama_url}/api/chat", json=payload)
                if response.status_code == 404:
                    logger.error(f"404 Not Found: Does the model '{self.model_name}' exist on the server?")
                    return None
                response.raise_for_status()
                result = response.json()
                return result.get("message", {}).get("content", "")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error querying model: {e}")
            return None

    async def _check_compression(self):
        if self.turn_count >= self.compression_threshold:
            logger.info("Compressing context...")
            if len(self.chat_history) > 4:
                self.chat_history = self.chat_history[-4:]
            self.turn_count = 0
