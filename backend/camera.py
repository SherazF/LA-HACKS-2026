import glob
import os
import platform
import time
import cv2
import threading
import logging
from typing import List, Callable, Optional, Tuple

logger = logging.getLogger(__name__)

CAMERA_WIDTH = int(os.getenv("CAMERA_WIDTH", "1920"))
CAMERA_HEIGHT = int(os.getenv("CAMERA_HEIGHT", "1080"))
CAMERA_FPS = int(os.getenv("CAMERA_FPS", "30"))
CAMERA_FOURCC = os.getenv("CAMERA_FOURCC", "MJPG").upper()


def _preferred_backend() -> int:
    """OpenCV's CAP_ANY auto-backend picks ffmpeg+v4l2 on Linux, which does
    NOT properly negotiate MJPG with most UVC webcams — we end up with raw
    YUYV that physically caps at ~5 fps for 1080p over USB. Forcing the
    real V4L2 backend lets MJPG actually apply, which is the difference
    between 5 fps and 30 fps for the same hardware.
    """
    if platform.system() == "Linux":
        return cv2.CAP_V4L2
    if platform.system() == "Darwin":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_ANY


def _configure_capture(cap: cv2.VideoCapture, source_label: str) -> None:
    """Push the camera to native HD@30 with MJPG so the V4L2 driver doesn't
    fall back to a tiny default like 640x480 @ 5 fps. We always set the
    fourcc FIRST — many UVC webcams refuse 1080p@30 in raw YUYV but accept
    it in MJPG. Logs the actual values the driver settled on so we can
    diagnose mismatches without sshing in.
    """
    if CAMERA_FOURCC and len(CAMERA_FOURCC) == 4:
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*CAMERA_FOURCC))
        except Exception:
            logger.debug("Failed to set FOURCC=%s on %s", CAMERA_FOURCC, source_label, exc_info=True)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
    # Request a small kernel-side buffer so we always grab the freshest
    # frame instead of a stale one queued behind reads (helps perceived
    # latency on slow consumers).
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc_str = (
        bytes([(actual_fourcc >> 8 * i) & 0xFF for i in range(4)]).decode("ascii", errors="replace")
        if actual_fourcc
        else "????"
    )
    logger.info(
        "Camera %s configured: requested %dx%d@%d %s, got %dx%d@%.1f %s",
        source_label,
        CAMERA_WIDTH,
        CAMERA_HEIGHT,
        CAMERA_FPS,
        CAMERA_FOURCC,
        actual_w,
        actual_h,
        actual_fps,
        fourcc_str,
    )


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
        backend = _preferred_backend()

        def try_cap(opener) -> Tuple[Optional[cv2.VideoCapture], str]:
            cap = opener()
            if cap.isOpened():
                return cap, "ok"
            cap.release()
            return None, ""

        if isinstance(self.camera_index, int):
            dev = f"/dev/video{self.camera_index}"
            if os.path.exists(dev):
                c, _ = try_cap(lambda: cv2.VideoCapture(self.camera_index, backend))
                if c is not None:
                    _configure_capture(c, f"index={self.camera_index}")
                    return c, "direct"
        else:
            c, _ = try_cap(lambda: cv2.VideoCapture(self.camera_index, backend))
            if c is not None:
                _configure_capture(c, f"path={self.camera_index}")
                return c, "direct"

        for path in video_nodes:
            c, _ = try_cap(lambda p=path: cv2.VideoCapture(p, backend))
            if c is not None:
                _configure_capture(c, f"auto={path}")
                return c, f"auto:{path}"
        return None, "none"

    def start(self):
        self.cap, source = self._open_capture()
        if self.cap is None or not self.cap.isOpened():
            logger.error(
                "Failed to open camera (index=%s); tried auto-fallback to /dev/video*",
                self.camera_index,
            )
            return

        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info("Camera stream started (source=%s)", source)

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
