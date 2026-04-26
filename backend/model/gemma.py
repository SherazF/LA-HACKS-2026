import asyncio
import base64
import json
import logging
import os
import re
from typing import Any, Dict, Optional

import cv2
import httpx

from bus import EventBus
from overlay_state import OverlayState

from .context import ContextManager

logger = logging.getLogger(__name__)

# Image is downsized before encoding. Gemma 3/4 vision tokenizes to a fixed
# patch grid regardless of source resolution, so going much above ~1024px wastes
# bandwidth without improving recognition. 16:9 to match typical webcams.
IMAGE_RESOLUTION = (1024, 576)

# JPEG quality: high enough to preserve fine cabling/text, low enough to keep
# the websocket / httpx payloads reasonable.
JPEG_QUALITY = 88

# Ollama generation options. Vision models with structured JSON output are
# very sensitive to temperature; gemma4's default is 1.0 which causes
# hallucinations and broken JSON. Lower temp + lower top_p stabilizes both
# the JSON shape and the visual reasoning. num_predict caps runaway monologues.
GENERATION_OPTIONS = {
    "temperature": 0.15,
    "top_p": 0.85,
    "top_k": 40,
    "repeat_penalty": 1.1,
    "num_predict": 512,
    "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "16384")),
}


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
        self.queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.context = ContextManager(token_limit=int(os.getenv("CONTEXT_TOKEN_LIMIT", "16000")))
        self.processing_lock = asyncio.Lock()
        self.current_task: Optional[asyncio.Task] = None
        self._snapshot_queued = False

        self.prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
        self.system_prompt_tpl = self._load_prompt("system_prompt.txt")
        self.snapshot_prompt_tpl = self._load_prompt("snapshot_prompt.txt")
        self.initial_request_tpl = self._load_prompt("initial_request.txt")
        self.known_parts = self._load_prompt("known_parts.txt")

        self.bus.subscribe("snapshot_ready", self.on_snapshot_ready)
        self.bus.subscribe("chat_input", self.on_chat_input)

    def _load_prompt(self, filename: str) -> str:
        path = os.path.join(self.prompt_dir, filename)
        try:
            with open(path, "r") as f:
                return f.read()
        except Exception as e:
            logger.error("Failed to load prompt %s: %s", filename, e)
            return ""

    async def _check_connection(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.ollama_url}/api/tags")
                if response.status_code == 200:
                    models = [m["name"] for m in response.json().get("models", [])]
                    logger.info("Connected to Ollama. Models available: %s", models)
                    if self.model_name not in models:
                        logger.warning(
                            "Configured model %s is NOT in Ollama; first request will likely fail",
                            self.model_name,
                        )
                else:
                    logger.error("Ollama server returned status %s", response.status_code)
        except Exception as e:
            logger.error("Could not connect to Ollama at %s: %s", self.ollama_url, e)

    def _add_frame_to_context(self, frame) -> None:
        """Resize the latest camera frame and stash it as the only visual input.

        We deliberately do NOT sharpen / contrast-stretch. Aggressive Unsharp
        Masking introduces ringing halos around edges that vision models trained
        on natural images often misinterpret as scratches, dirt, or extra parts.
        Vision models prefer raw camera output.
        """
        if frame is None:
            return
        target_w, target_h = IMAGE_RESOLUTION
        h, w = frame.shape[:2]
        # Preserve aspect ratio: scale to fit within the target box.
        scale = min(target_w / max(w, 1), target_h / max(h, 1))
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        if (new_w, new_h) != (w, h):
            frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

        ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if not ok:
            logger.warning("Failed to JPEG-encode frame; skipping image add")
            return
        img_str = base64.b64encode(buffer).decode("utf-8")
        self.context.add_image(img_str)
        logger.debug("Visual memory updated with %dx%d JPEG (%d bytes)", new_w, new_h, len(buffer))

    def _apply_overlays_from_response(self, data: Optional[Dict[str, Any]]) -> None:
        if not self.overlay_state or not data:
            return
        ops = data.get("overlay_operations")
        if isinstance(ops, list):
            self.overlay_state.apply_model_operations(ops)

    async def on_snapshot_ready(self, frame) -> None:
        if not self.context.is_initialized:
            return
        if self._snapshot_queued:
            logger.debug("Snapshot already queued, dropping new one")
            return
        self._snapshot_queued = True
        await self.queue.put((1, {"type": "snapshot", "frame": frame}))

    async def on_chat_input(self, text, frame=None) -> None:
        if frame is not None:
            self._add_frame_to_context(frame)
        await self.bus.emit("reset_snapshot_timer")
        await self.queue.put((0, {"type": "chat", "text": text}))
        if self.current_task and not self.current_task.done():
            logger.info("Chat preempting in-flight vision task...")
            self.current_task.cancel()

    async def start(self) -> None:
        logger.info("Model Manager started (Model: %s)", self.model_name)
        await self._check_connection()

        while True:
            try:
                priority, item = await self.queue.get()

                try:
                    async with self.processing_lock:
                        if item["type"] == "chat":
                            await self._process_chat(item["text"])
                        elif item["type"] == "snapshot":
                            self._snapshot_queued = False
                            # Skip stale snapshots if a chat is queued behind us.
                            if not self.queue.empty():
                                next_prio, _ = self.queue._queue[0]
                                if next_prio < priority:
                                    logger.info("Skipping snapshot for pending chat")
                                    continue

                            self.current_task = asyncio.create_task(
                                self._process_snapshot(item["frame"])
                            )
                            try:
                                await self.current_task
                            except asyncio.CancelledError:
                                logger.info("Vision task cancelled")
                            finally:
                                self.current_task = None
                finally:
                    self.queue.task_done()
                    await self.bus.emit("inference_done")
            except Exception as e:
                logger.error("Model Manager error (%s): %s", type(e).__name__, e, exc_info=True)
                await asyncio.sleep(0.1)

    async def _process_chat(self, text: str) -> None:
        if not self.context.is_initialized:
            logger.info("First chat message: initializing build session")
            prompt = self.initial_request_tpl.format(user_input=text)
            self.context.is_initialized = True
        else:
            prompt = text

        self.context.add_message("user", prompt)
        json_resp = await self._query_model()

        if json_resp:
            self.context.update_state(json_resp)
            self._apply_overlays_from_response(json_resp)
            response_text = (json_resp.get("response") or "").strip()
            # Safety net: user chat MUST get a response. If the model defied
            # the system prompt and returned "empty" anyway, fall back to a
            # short acknowledgement so the user isn't left hanging.
            if not response_text or response_text.lower() == "empty":
                logger.warning(
                    "Chat turn returned empty response; substituting fallback"
                )
                response_text = (
                    "Sorry, I caught that but couldn't form a clear answer from what I'm "
                    "seeing. Can you rephrase or move the camera a bit?"
                )
            if self.context.add_message("assistant", response_text):
                await self.bus.emit("chat_response", text=response_text)
        else:
            fallback = (
                "I lost the connection to the model for a moment — please try that again."
            )
            await self.bus.emit("chat_response", text=fallback)

    async def _process_snapshot(self, frame) -> None:
        """Run a transient vision turn that does not pollute chat history.

        Only the model's substantive response (if any) is added to history,
        so the user-visible chat panel stays coherent and the model isn't
        distracted by long sequences of its own analysis prompts.
        """
        self._add_frame_to_context(frame)

        json_resp = await self._query_model(transient_prompt=self.snapshot_prompt_tpl)
        if not json_resp:
            return

        self.context.update_state(json_resp)
        self._apply_overlays_from_response(json_resp)
        response_text = (json_resp.get("response") or "").strip()
        if response_text and response_text.lower() != "empty":
            if self.context.add_message("assistant", response_text):
                await self.bus.emit("vision_result", text=response_text)

    async def _query_model(self, transient_prompt: Optional[str] = None) -> Optional[Dict]:
        formatted_state = self.context.get_formatted_state()
        # Auto-evict overlays the model forgot to clear so they don't pile up
        # forever, then describe whatever is still on screen so the model can
        # decide whether to keep, replace, or clear them this turn.
        if self.overlay_state is not None:
            cleared = self.overlay_state.clear_stale()
            if cleared:
                logger.info("Auto-cleared %d stale overlay(s)", cleared)
            active_overlays = self.overlay_state.describe_active()
        else:
            active_overlays = "none"

        try:
            system_prompt = self.system_prompt_tpl.format(
                known_parts=self.known_parts,
                milestones=formatted_state["milestones"],
                parts=formatted_state["parts"],
                current_objectives=formatted_state["current_objectives"],
                active_overlays=active_overlays,
            )
        except KeyError as e:
            logger.error("KeyError in system_prompt.format: %s", e)
            logger.error(
                "Available placeholders in system_prompt: %s",
                re.findall(r"\{([^}]+)\}", self.system_prompt_tpl),
            )
            raise

        messages = self.context.get_messages_payload(system_prompt, transient_prompt)

        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": GENERATION_OPTIONS,
            # Disable Ollama's "thinking" mode for gemma4 — when on, Ollama
            # buries the JSON in the `thinking` channel and `content` comes back
            # blank, making the model look completely silent.
            "think": False,
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(f"{self.ollama_url}/api/chat", json=payload)
                    response.raise_for_status()
                    result = response.json()
                    content = (result.get("message") or {}).get("content", "")
                    if not content.strip():
                        logger.warning(
                            "Attempt %d: model returned empty content (eval_count=%s)",
                            attempt + 1,
                            result.get("eval_count"),
                        )
                        if attempt == max_retries - 1:
                            return None
                        continue
                    parsed = self._extract_json(content)
                    if parsed is not None:
                        logger.info("Full model response: %s", json.dumps(parsed, indent=2))
                        return parsed
                    logger.warning(
                        "Attempt %d: failed to parse JSON content: %r", attempt + 1, content[:400]
                    )
                    if attempt == max_retries - 1:
                        return None
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 500:
                    logger.warning("Attempt %d: server returned 500", attempt + 1)
                    if attempt == max_retries - 1:
                        return None
                else:
                    logger.error("HTTP error: %s", e)
                    return None
            except (httpx.RequestError, asyncio.TimeoutError) as e:
                logger.warning("Attempt %d: request failed: %s", attempt + 1, e)
                if attempt == max_retries - 1:
                    return None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Unexpected error querying model: %s", e)
                return None

            if attempt < max_retries - 1:
                await asyncio.sleep(1.0)

        return None

    @staticmethod
    def _extract_json(content: str) -> Optional[Dict]:
        """Try a strict json.loads first, then fall back to the first {...} block.

        Even with `format=json`, Gemma occasionally prefixes the JSON with a
        stray newline or a leftover token. Salvaging the first balanced object
        keeps the loop alive instead of silently dropping turns.
        """
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        m = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
