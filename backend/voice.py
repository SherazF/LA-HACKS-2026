import asyncio
import logging
import threading
from typing import List, Optional

import speech_recognition as sr

from bus import EventBus

logger = logging.getLogger(__name__)


class VoiceInputManager:
    """Backend microphone capture and speech-to-text using PyAudio."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._lock = asyncio.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._chunks: List[str] = []
        self._thread_error: Optional[str] = None
        self._is_listening = False

        self._bus.subscribe("voice_start", self.on_voice_start)
        self._bus.subscribe("voice_stop", self.on_voice_stop)

    async def on_voice_start(self) -> None:
        async with self._lock:
            if self._is_listening:
                return
            self._chunks = []
            self._thread_error = None
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread.start()
            self._is_listening = True

        await self._bus.emit("voice_state", listening=True)

    async def on_voice_stop(self) -> None:
        thread_to_join: Optional[threading.Thread] = None
        async with self._lock:
            if not self._is_listening:
                await self._bus.emit("voice_state", listening=False)
                return
            self._stop_event.set()
            thread_to_join = self._thread

        if thread_to_join is not None:
            await asyncio.to_thread(thread_to_join.join, 5.0)

        async with self._lock:
            self._is_listening = False
            transcript = " ".join(chunk for chunk in self._chunks if chunk).strip()
            thread_error = self._thread_error
            self._thread = None
            self._chunks = []
            self._thread_error = None

        await self._bus.emit("voice_state", listening=False)
        if thread_error:
            await self._bus.emit("voice_error", message=thread_error)
            return
        if transcript:
            await self._bus.emit("voice_transcript", text=transcript)
        else:
            await self._bus.emit("voice_error", message="No speech detected. Try again.")

    def _capture_loop(self) -> None:
        recognizer = sr.Recognizer()
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.4)
                while not self._stop_event.is_set():
                    try:
                        audio = recognizer.listen(source, timeout=0.5, phrase_time_limit=8)
                    except sr.WaitTimeoutError:
                        continue

                    if self._stop_event.is_set():
                        break

                    try:
                        text = recognizer.recognize_google(audio)
                    except sr.UnknownValueError:
                        continue
                    except sr.RequestError as exc:
                        self._thread_error = f"Speech recognition service error: {exc}"
                        break

                    text = (text or "").strip()
                    if text:
                        self._chunks.append(text)
        except Exception as exc:
            logger.exception("Voice capture failed")
            self._thread_error = f"Microphone error: {exc}"
