import asyncio
import argparse
import logging
import os
from dotenv import load_dotenv
from bus import EventBus
from camera import CameraStream
from gemma import ModelManager
from snapshot import SnapshotManager
from chat import ChatManager
from ui import UIManager

load_dotenv()
OLLAMA_HOST = os.getenv("OLLAMA_HOST") or "localhost"
OLLAMA_PORT = os.getenv("OLLAMA_PORT") or 11434
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL") or "gemma4:e2b"
CAMERA_INDEX = int(os.getenv("CAMERA_INDEX") or 0)

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Main")

async def async_main(args):
    bus = EventBus()
    camera = CameraStream(camera_index=CAMERA_INDEX)
    # Pass the model name to ModelManager
    ollama_url = f'http://{OLLAMA_HOST}:{OLLAMA_PORT}'
    model_manager = ModelManager(bus, ollama_url=ollama_url, model_name=OLLAMA_MODEL)
    snapshot_manager = SnapshotManager(bus, camera, interval=args.snapshot_interval)
    chat_manager = ChatManager(bus)
    ui_manager = UIManager(bus)

    # Register UI to receive camera frames directly
    camera.register_ui_callback(ui_manager.on_frame)

    # Stop event to coordinate shutdown
    stop_event = asyncio.Event()
    
    async def quit_handler():
        logger.info("Quit event received, signaling shutdown...")
        stop_event.set()

    bus.subscribe("quit", quit_handler)

    # Start components
    camera.start()
    
    # Run background managers
    tasks = [
        asyncio.create_task(model_manager.start()),
        asyncio.create_task(snapshot_manager.start()),
        asyncio.create_task(chat_manager.start()),
        asyncio.create_task(ui_manager.start())
    ]

    try:
        # Wait until stop_event is set or one of the tasks finishes (like UI closing)
        done, pending = await asyncio.wait(
            [asyncio.create_task(stop_event.wait())] + tasks,
            return_when=asyncio.FIRST_COMPLETED
        )
    except asyncio.CancelledError:
        logger.info("Main task cancelled")
    finally:
        logger.info("Shutting down...")
        camera.stop()
        for task in tasks:
            if not task.done():
                task.cancel()
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Shutdown complete")

def main():
    parser = argparse.ArgumentParser(description="PC Build Guidance App")
    parser.add_argument("--snapshot-interval", type=float, default=15.0, help="Interval between snapshots in seconds")
    args = parser.parse_args()

    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")

if __name__ == "__main__":
    main()
