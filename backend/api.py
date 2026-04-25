import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from bus import EventBus
from camera import CameraStream
from chat import ChatManager
from gemma import ModelManager
from snapshot import SnapshotManager
from ui import UIManager
from ws_bridge import ConnectionManager, WebSocketBridge, handle_websocket, run_camera_frame_stream

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("api")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
OLLAMA_PORT = os.getenv("OLLAMA_PORT", "11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b")
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
SNAPSHOT_INTERVAL = float(os.getenv("SNAPSHOT_INTERVAL", "15.0"))
CAMERA_STREAM_FPS = float(os.getenv("CAMERA_STREAM_FPS", "12"))


def _truthy(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    shutdown = asyncio.Event()
    bus = EventBus()
    camera = CameraStream(camera_index=CAMERA_INDEX)
    camera.start()

    ollama_url = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
    model_manager = ModelManager(bus, ollama_url=ollama_url, model_name=OLLAMA_MODEL)
    snapshot_manager = SnapshotManager(bus, camera, interval=SNAPSHOT_INTERVAL)
    connection_manager = ConnectionManager()
    bridge = WebSocketBridge(bus, connection_manager)
    bridge.register()

    app.state.bus = bus
    app.state.camera = camera
    app.state.model_manager = model_manager
    app.state.connection_manager = connection_manager
    app.state.shutdown = shutdown

    background_tasks: List[asyncio.Task] = []
    background_tasks.append(asyncio.create_task(model_manager.start(), name="model_manager"))
    background_tasks.append(asyncio.create_task(snapshot_manager.start(), name="snapshot_manager"))
    background_tasks.append(
        asyncio.create_task(
            run_camera_frame_stream(
                connection_manager, camera, shutdown, CAMERA_STREAM_FPS
            ),
            name="camera_stream",
        )
    )

    if _truthy("ENABLE_CONSOLE_CHAT", "0"):
        chat = ChatManager(bus)
        background_tasks.append(asyncio.create_task(chat.start(), name="console_chat"))
        logger.info("Console chat manager enabled (ENABLE_CONSOLE_CHAT)")

    if _truthy("ENABLE_OPENCV_UI", "0"):
        ui = UIManager(bus)
        camera.register_ui_callback(ui.on_frame)
        background_tasks.append(asyncio.create_task(ui.start(), name="opencv_ui"))
        logger.info("OpenCV UI enabled (ENABLE_OPENCV_UI)")

    try:
        yield
    finally:
        logger.info("Shutting down application...")
        shutdown.set()
        for t in background_tasks:
            t.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        camera.stop()
        logger.info("Shutdown complete")


app = FastAPI(lifespan=lifespan, title="PC Build Guidance API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    image: str = Field(..., description="Data URL or base64 image from the client")


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    # Placeholder for a future vision / detection pipeline; keeps Electron compatibility.
    _ = req.image
    return {"boxes": []}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    bus: EventBus = websocket.app.state.bus
    connection_manager: ConnectionManager = websocket.app.state.connection_manager
    await handle_websocket(websocket, bus, connection_manager)
