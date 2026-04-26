import asyncio
import json
import logging
from typing import Set

import cv2
from fastapi import WebSocket, WebSocketDisconnect

from bus import EventBus
from camera import CameraStream

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks active WebSocket clients; broadcasts JSON text or JPEG binary."""

    def __init__(self) -> None:
        self._active: Set[WebSocket] = set()

    def has_clients(self) -> bool:
        return bool(self._active)

    @property
    def client_count(self) -> int:
        return len(self._active)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._active.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._active.discard(websocket)

    async def send_json(self, websocket: WebSocket, payload: dict) -> None:
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception:
            self.disconnect(websocket)
            raise

    async def broadcast_json(self, payload: dict) -> None:
        if not self._active:
            return
        text = json.dumps(payload)
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

    async def _on_voice_state(self, listening: bool) -> None:
        await self._manager.broadcast_json({"v": 1, "type": "voice_state", "listening": bool(listening)})


async def run_camera_frame_stream(
    manager: ConnectionManager,
    camera: CameraStream,
    shutdown: asyncio.Event,
    fps: float,
) -> None:
    """Encode latest OpenCV frame as JPEG and broadcast while clients are connected."""
    interval = 1.0 / max(fps, 0.1)
    while not shutdown.is_set():
        if manager.has_clients():
            frame = camera.get_latest_frame()
            if frame is not None:
                ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
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
                    await bus.emit("chat_input", text=text)
            elif mtype == "voice_start":
                await bus.emit("voice_start")
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
