import cv2
import threading
import time
import logging
from typing import List, Callable

logger = logging.getLogger(__name__)

class CameraStream:
    def __init__(self, camera_index=0):
        self.camera_index = camera_index
        self.cap = None
        self.latest_frame = None
        self.running = False
        self.thread = None
        self._ui_callbacks: List[Callable] = []
        self._lock = threading.Lock()

    def register_ui_callback(self, callback: Callable):
        self._ui_callbacks.append(callback)

    def start(self):
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            logger.error(f"Failed to open camera {self.camera_index}")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info("Camera stream started")

    def _run(self):
        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                logger.warning("Failed to grab frame")
                time.sleep(0.1)
                continue

            with self._lock:
                self.latest_frame = frame.copy()

            for callback in self._ui_callbacks:
                callback(frame)

    def get_latest_frame(self):
        with self._lock:
            return self.latest_frame.copy() if self.latest_frame is not None else None

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
        if self.cap:
            self.cap.release()
        logger.info("Camera stream stopped")
