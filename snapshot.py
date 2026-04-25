import asyncio
import logging
from bus import EventBus
from camera import CameraStream

logger = logging.getLogger(__name__)

class SnapshotManager:
    def __init__(self, bus: EventBus, camera: CameraStream, interval: float = 10.0):
        self.bus = bus
        self.camera = camera
        self.interval = interval
        self._inference_done_event = asyncio.Event()
        self._inference_done_event.set() # Start ready
        
        self.bus.subscribe("inference_done", self.on_inference_done)

    def on_inference_done(self):
        self._inference_done_event.set()

    async def start(self):
        logger.info("Snapshot Manager started")
        while True:
            # Wait for previous inference to finish
            await self._inference_done_event.wait()
            self._inference_done_event.clear()
            
            # Wait for the interval
            await asyncio.sleep(self.interval)
            
            frame = self.camera.get_latest_frame()
            if frame is not None:
                logger.info("Triggering snapshot")
                await self.bus.emit("snapshot_ready", frame=frame)
            else:
                logger.warning("No frame available for snapshot")
                self._inference_done_event.set() # Reset if failed to get frame
