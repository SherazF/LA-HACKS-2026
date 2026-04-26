import glob
import os
import time
import cv2
import threading
import logging
from typing import List, Callable, Optional, Tuple

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

    def _open_capture(self) -> Tuple[Optional[cv2.VideoCapture], str]:
        """Try requested index/path, then first working /dev/video* (e.g. no /dev/video0)."""
        video_nodes = sorted(glob.glob("/dev/video*"))

        def try_cap(opener) -> Tuple[Optional[cv2.VideoCapture], str]:
            cap = opener()
            if cap.isOpened():
                return cap, "ok"
            cap.release()
            return None, ""

        # 1) Requested index (int or string path). Skip missing /dev/videoN to avoid useless V4L errors.
        c, _ = None, ""
        if isinstance(self.camera_index, int):
            dev = f"/dev/video{self.camera_index}"
            if os.path.exists(dev):
                c, _ = try_cap(lambda: cv2.VideoCapture(self.camera_index))
        else:
            c, _ = try_cap(lambda: cv2.VideoCapture(self.camera_index))
        if c is not None:
            return c, "direct"

        # 2) Auto: first working /dev/video*
        for path in video_nodes:
            c, _ = try_cap(lambda p=path: cv2.VideoCapture(p))
            if c is not None:
                return c, f"auto:{path}"
        return None, "none"

    def start(self):
        self.cap, _ = self._open_capture()
        if self.cap is None or not self.cap.isOpened():
            logger.error("Failed to open camera (index=%s); tried auto-fallback to /dev/video*", self.camera_index)
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
