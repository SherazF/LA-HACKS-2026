import asyncio
import collections
import json
import logging
import os
import time
from typing import Deque, Optional, Set

import cv2
from fastapi import WebSocket, WebSocketDisconnect

from bus import EventBus
from camera import CameraStream
from overlay_state import OverlayState, render_overlays

logger = logging.getLogger(__name__)

CAMERA_STREAM_JPEG_QUALITY = int(os.getenv("CAMERA_STREAM_JPEG_QUALITY", "92"))

# Tiny ring buffer of recent assistant messages so a client that reconnects
# mid-reply doesn't silently lose the model's response. Capped at N entries
# AND by age so the chat doesn't fill with stale stuff on a long reconnect.
REPLAY_BUFFER_SIZE = 20
REPLAY_MAX_AGE_SECONDS = 30.0

# Message types worth replaying when a client (re)connects. Transient signals
# (voice_state, pong, status) only make sense in the moment.
REPLAYABLE_TYPES = {"chat_response", "vision_result", "voice_transcript"}


class ConnectionManager:
    """Tracks active WebSocket clients; broadcasts JSON text or JPEG binary.

    Maintains a small ring buffer of recent replayable messages so a client
    that reconnects mid-reply doesn't silently lose the model's response.
    """

    def __init__(self) -> None:
        self._active: Set[WebSocket] = set()
        # (monotonic_ts, payload) pairs.
        self._replay: Deque[tuple[float, dict]] = collections.deque(
            maxlen=REPLAY_BUFFER_SIZE
        )

    def has_clients(self) -> bool:
        return bool(self._active)

    @property
    def client_count(self) -> int:
        return len(self._active)

    def _fresh_replay(self) -> list[dict]:
        cutoff = time.monotonic() - REPLAY_MAX_AGE_SECONDS
        return [p for ts, p in self._replay if ts >= cutoff]

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._active.add(websocket)
        fresh = self._fresh_replay()
        if fresh:
            logger.info(
                "Replaying %d buffered message(s) to new client", len(fresh)
            )
            for past in fresh:
                try:
                    await websocket.send_text(json.dumps(past))
                except Exception:
                    self.disconnect(websocket)
                    return

    def disconnect(self, websocket: WebSocket) -> None:
        self._active.discard(websocket)

    async def send_json(self, websocket: WebSocket, payload: dict) -> None:
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception:
            self.disconnect(websocket)
            raise

    async def broadcast_json(self, payload: dict) -> None:
        if payload.get("type") in REPLAYABLE_TYPES:
            self._replay.append((time.monotonic(), payload))
        if not self._active:
            if payload.get("type") in REPLAYABLE_TYPES:
                logger.warning(
                    "No WS clients connected — buffered for replay (type=%s)",
                    payload.get("type"),
                )
            return
        text = json.dumps(payload)
        logger.info(
            "Broadcasting JSON to %d client(s) (type=%s)",
            len(self._active),
            payload.get("type"),
        )
        dead: list[WebSocket] = []
        for ws in list(self._active):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_bytes(self, data: bytes) -> None:
        if not self._active or not data:
            return
        logger.debug(f"Broadcasting bytes to {len(self._active)} client(s)")
        dead: list[WebSocket] = []
        for ws in list(self._active):
            try:
                await ws.send_bytes(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


class WebSocketBridge:
    """Forwards bus events to all WebSocket clients."""

    def __init__(self, bus: EventBus, manager: ConnectionManager) -> None:
        self._bus = bus
        self._manager = manager
        self._registered = False

    def register(self) -> None:
        if self._registered:
            return
        self._bus.subscribe("vision_result", self._on_vision_result)
        self._bus.subscribe("chat_response", self._on_chat_response)
        self._bus.subscribe("voice_transcript", self._on_voice_transcript)
        self._bus.subscribe("voice_error", self._on_voice_error)
        self._bus.subscribe("voice_state", self._on_voice_state)
        self._registered = True

    async def _on_vision_result(self, text: str) -> None:
        await self._manager.broadcast_json({"v": 1, "type": "vision_result", "text": text})

    async def _on_chat_response(self, text: str) -> None:
        await self._manager.broadcast_json({"v": 1, "type": "chat_response", "text": text})

    async def _on_voice_transcript(self, text: str) -> None:
        await self._manager.broadcast_json({"v": 1, "type": "voice_transcript", "text": text})

    async def _on_voice_error(self, message: str) -> None:
        await self._manager.broadcast_json({"v": 1, "type": "voice_error", "message": message})

    async def _on_voice_state(self, listening: bool, mode: str = "manual") -> None:
        await self._manager.broadcast_json(
            {
                "v": 1,
                "type": "voice_state",
                "listening": bool(listening),
                "mode": mode,
            }
        )


async def run_camera_frame_stream(
    manager: ConnectionManager,
    camera: CameraStream,
    shutdown: asyncio.Event,
    fps: float,
    overlay_state: Optional[OverlayState] = None,
) -> None:
    """Encode latest OpenCV frame as JPEG and broadcast while clients are connected.

    Overlays are drawn on a copy of the frame (see overlay_state / docs).
    """
    interval = 1.0 / max(fps, 0.1)
    while not shutdown.is_set():
        if manager.has_clients():
            frame = camera.get_latest_frame()
            if frame is not None:
                vis = render_overlays(frame, overlay_state)
                ok, buf = cv2.imencode(
                    ".jpg",
                    vis,
                    [int(cv2.IMWRITE_JPEG_QUALITY), CAMERA_STREAM_JPEG_QUALITY],
                )
                if ok:
                    await manager.broadcast_bytes(buf.tobytes())
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            pass


async def handle_websocket(
    websocket: WebSocket,
    bus: EventBus,
    manager: ConnectionManager,
) -> None:
    await manager.connect(websocket)
    try:
        await manager.send_json(
            websocket, {"v": 1, "type": "status", "message": "ready"}
        )
    except Exception:
        manager.disconnect(websocket)
        return

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await manager.send_json(
                    websocket,
                    {"v": 1, "type": "error", "message": "invalid JSON"},
                )
                continue

            v = msg.get("v", 0)
            if v != 1:
                await manager.send_json(
                    websocket,
                    {"v": 1, "type": "error", "message": f"unsupported protocol v={v!r}"},
                )
                continue

            mtype = msg.get("type")
            if mtype == "ping":
                await manager.send_json(websocket, {"v": 1, "type": "pong"})
            elif mtype == "chat":
                text = (msg.get("text") or "").strip()
                if text:
                    # Pull latest frame from the existing backend camera resource
                    frame = websocket.app.state.camera.get_latest_frame()
                    await bus.emit("chat_input", text=text, frame=frame)
            elif mtype == "voice_start":
                mode = (msg.get("mode") or "manual").lower()
                if mode not in ("manual", "auto"):
                    mode = "manual"
                await bus.emit("voice_start", mode=mode)
            elif mtype == "voice_stop":
                await bus.emit("voice_stop")
            else:
                await manager.send_json(
                    websocket,
                    {
                        "v": 1,
                        "type": "error",
                        "message": f"unknown type: {mtype!r}",
                    },
                )
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
