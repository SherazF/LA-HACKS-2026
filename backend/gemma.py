import asyncio
import logging
import httpx
import json
import base64
import cv2
import os
from datetime import datetime
from typing import Dict, List, Optional
from bus import EventBus

logger = logging.getLogger(__name__)

class ModelManager:
    def __init__(self, bus: EventBus, ollama_url: str = "http://localhost:11434", model_name: str = "gemma", 
                 input_dir: str = "inputs", output_dir: str = "outputs"):
        self.bus = bus
        self.ollama_url = ollama_url.rstrip('/')
        self.model_name = model_name
        self.queue = asyncio.PriorityQueue()
        self.chat_history: List[Dict] = []
        self.input_dir = input_dir
        self.output_dir = output_dir
        
        # Create directories if they don't exist
        os.makedirs(self.input_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Enhanced system prompt for better structured markdown output
        self.system_prompt = """You are a helpful assistant that provides clear, step-by-step guidance.

IMPORTANT: Format all responses as clean, professional Markdown with:
- Clear headings (## for main sections, ### for subsections)
- Numbered steps for procedures
- Bullet points for lists and details
- Code blocks (```language ... ```) for commands or code
- Bold for important terms (**bold**)
- Proper spacing between sections

Always structure your response to be easy to read and follow, with clear organization and proper Markdown formatting."""
        
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

    def read_input_file(self, filename: str = "input.txt") -> Optional[str]:
        """Read input from a .txt file."""
        filepath = os.path.join(self.input_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            if content:
                logger.info(f"Successfully read input from {filepath}")
                return content
            else:
                logger.warning(f"Input file is empty: {filepath}")
                return None
        except FileNotFoundError:
            logger.error(f"Input file not found: {filepath}")
            return None
        except Exception as e:
            logger.error(f"Error reading input file: {e}")
            return None

    def write_output_file(self, content: str, filename: Optional[str] = None) -> str:
        """Write formatted output to a .md file."""
        if filename is None:
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"output_{timestamp}.md"
        
        filepath = os.path.join(self.output_dir, filename)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"Successfully wrote output to {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Error writing output file: {e}")
            return None

    async def process_file_input(self, input_filename: str = "input.txt", 
                                 output_filename: Optional[str] = None) -> Dict:
        """Process file-based input and generate formatted markdown output."""
        logger.info(f"Starting file-based input processing")
        
        # Read input
        prompt = self.read_input_file(input_filename)
        if not prompt:
            error_msg = f"Could not read input from {input_filename}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
        
        # Query model
        response = await self._query_model_for_file(prompt)
        if not response:
            error_msg = "Model returned empty response"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
        
        # Format and write output
        formatted_output = self._format_markdown_output(prompt, response)
        output_path = self.write_output_file(formatted_output, output_filename)
        
        if output_path:
            return {
                "success": True,
                "input_file": os.path.join(self.input_dir, input_filename),
                "output_file": output_path,
                "prompt": prompt,
                "response": response
            }
        else:
            return {"success": False, "error": "Failed to write output file"}

    def _format_markdown_output(self, prompt: str, response: str) -> str:
        """Format the output with metadata and proper markdown structure."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Add header with metadata
        markdown_output = f"""# Generated Output

**Generated:** {timestamp}  
**Model:** {self.model_name}

---

## Input Prompt

{prompt}

---

## Response

{response}

---

*Generated by Gemma Model Manager*
"""
        return markdown_output

    async def _query_model_for_file(self, prompt: str) -> Optional[str]:
        """Query the model without chat history (for file-based processing)."""
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt}
            ],
            "stream": False
        }

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
