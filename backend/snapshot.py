import asyncio
import logging
from bus import EventBus
from camera import CameraStream

logger = logging.getLogger(__name__)

class SnapshotManager:
    def __init__(self, bus: EventBus, camera: CameraStream, interval: float = 60):
        self.bus = bus
        self.camera = camera
        self.interval = interval
        self._inference_done_event = asyncio.Event()
        self._inference_done_event.set() # Start ready
        self._reset_event = asyncio.Event()
        
        self.bus.subscribe("inference_done", self.on_inference_done)
        self.bus.subscribe("reset_snapshot_timer", self.on_reset_timer)

    def on_inference_done(self):
        self._inference_done_event.set()

    def on_reset_timer(self):
        logger.info("Snapshot timer reset requested")
        self._reset_event.set()

    async def start(self):
        logger.info("Snapshot Manager started")
        while True:
            # Wait for previous inference to finish
            await self._inference_done_event.wait()
            self._inference_done_event.clear()
            self._reset_event.clear()
            
            # Wait for the interval, but allow interruption
            try:
                # Use wait_for on the reset event with a timeout equal to the interval
                await asyncio.wait_for(self._reset_event.wait(), timeout=self.interval)
                logger.info("Snapshot timer interrupted by chat, restarting interval...")
                self._inference_done_event.set() # Mark as "done" so we cycle immediately
                continue # Go back to start of loop to wait again
            except asyncio.TimeoutError:
                # Normal interval elapsed
                pass
            
            frame = self.camera.get_latest_frame()
            if frame is not None:
                logger.info("Triggering snapshot")
                await self.bus.emit("snapshot_ready", frame=frame)
            else:
                logger.warning("No frame available for snapshot")
                self._inference_done_event.set()
