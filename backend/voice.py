import asyncio
import array
import logging
import os
import tempfile
import threading
import wave
from typing import Optional

import pyaudio
import speech_recognition as sr

from bus import EventBus

logger = logging.getLogger(__name__)

VOICE_CHUNK_SIZE = int(os.getenv("VOICE_CHUNK_SIZE", "1024"))
VOICE_SAMPLE_RATE = int(os.getenv("VOICE_SAMPLE_RATE", "0"))
VOICE_MIN_SECONDS = float(os.getenv("VOICE_MIN_SECONDS", "0.35"))
VOICE_MIN_RMS = int(os.getenv("VOICE_MIN_RMS", "80"))
VOICE_STT_ENGINE = os.getenv("VOICE_STT_ENGINE", "whisper").lower()
VOICE_WHISPER_MODEL = os.getenv("VOICE_WHISPER_MODEL", "small.en")
VOICE_WHISPER_COMPUTE_TYPE = os.getenv("VOICE_WHISPER_COMPUTE_TYPE", "int8")
VOICE_INPUT_DEVICE_INDEX = os.getenv("VOICE_INPUT_DEVICE_INDEX")
VOICE_PREFER_BUILTIN_MIC = os.getenv("VOICE_PREFER_BUILTIN_MIC", "1").lower() in (
    "1",
    "true",
    "yes",
)


class VoiceInputManager:
    """Backend microphone capture and speech-to-text using PyAudio."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._lock = asyncio.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._audio_bytes = b""
        self._sample_rate = 16000
        self._sample_width = 2
        self._thread_error: Optional[str] = None
        self._is_listening = False
        self._whisper_model = None

        self._bus.subscribe("voice_start", self.on_voice_start)
        self._bus.subscribe("voice_stop", self.on_voice_stop)

    async def on_voice_start(self) -> None:
        async with self._lock:
            if self._is_listening:
                return
            self._audio_bytes = b""
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
            audio_bytes = self._audio_bytes
            sample_rate = self._sample_rate
            sample_width = self._sample_width
            thread_error = self._thread_error
            self._thread = None
            self._audio_bytes = b""
            self._thread_error = None

        await self._bus.emit("voice_state", listening=False)
        if thread_error:
            await self._bus.emit("voice_error", message=thread_error)
            return
        if len(audio_bytes) < int(sample_rate * sample_width * VOICE_MIN_SECONDS):
            await self._bus.emit("voice_error", message="No speech detected. Try again.")
            return
        rms, peak = self._audio_levels(audio_bytes, sample_width)
        duration = len(audio_bytes) / float(sample_rate * sample_width)
        logger.info(
            "Captured %.2fs voice audio (%d bytes, rate=%d, rms=%d, peak=%d)",
            duration,
            len(audio_bytes),
            sample_rate,
            rms,
            peak,
        )
        if rms < VOICE_MIN_RMS:
            await self._bus.emit(
                "voice_error",
                message=(
                    "No speech detected. The microphone captured mostly silence "
                    f"(level {rms}). Check mic input or speak closer."
                ),
            )
            return

        transcript, error = await asyncio.to_thread(
            self._transcribe_offline,
            audio_bytes,
            sample_rate,
            sample_width,
        )
        if error:
            await self._bus.emit("voice_error", message=error)
            return
        if transcript:
            await self._bus.emit("voice_transcript", text=transcript)
        else:
            await self._bus.emit("voice_error", message="No speech detected. Try again.")

    def _capture_loop(self) -> None:
        audio = pyaudio.PyAudio()
        stream = None
        frames: list[bytes] = []
        try:
            input_device_index, input_device = self._select_input_device(audio)
            sample_rate = VOICE_SAMPLE_RATE or int(input_device.get("defaultSampleRate", 16000))
            sample_width = audio.get_sample_size(pyaudio.paInt16)
            logger.info(
                "Opening voice input: %s (index=%s, rate=%d)",
                input_device.get("name"),
                input_device.get("index"),
                sample_rate,
            )
            stream = audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=sample_rate,
                input=True,
                input_device_index=input_device_index,
                frames_per_buffer=VOICE_CHUNK_SIZE,
            )

            while not self._stop_event.is_set():
                frames.append(stream.read(VOICE_CHUNK_SIZE, exception_on_overflow=False))

            self._sample_rate = sample_rate
            self._sample_width = sample_width
            self._audio_bytes = b"".join(frames)
        except Exception as exc:
            logger.exception("Voice capture failed")
            self._thread_error = f"Microphone error: {exc}"
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    logger.debug("Failed to close voice stream cleanly", exc_info=True)
            audio.terminate()

    def _transcribe_offline(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        sample_width: int,
    ) -> tuple[str, Optional[str]]:
        if VOICE_STT_ENGINE == "whisper":
            transcript, error = self._transcribe_with_whisper(
                audio_bytes,
                sample_rate,
                sample_width,
            )
            if transcript:
                return transcript, None
            if error:
                logger.warning("Falling back to PocketSphinx: %s", error)
            else:
                logger.warning("Whisper returned no text; falling back to PocketSphinx")

        recognizer = sr.Recognizer()
        audio_data = sr.AudioData(audio_bytes, sample_rate, sample_width)
        try:
            return recognizer.recognize_sphinx(audio_data).strip(), None
        except sr.UnknownValueError:
            return "", None
        except sr.RequestError as exc:
            return "", (
                "Offline speech recognition engine error. "
                f"Check that PocketSphinx is installed correctly: {exc}"
            )

    def _transcribe_with_whisper(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        sample_width: int,
    ) -> tuple[str, Optional[str]]:
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:
            return "", f"Whisper is not installed: {exc}"

        try:
            if self._whisper_model is None:
                logger.info("Loading offline Whisper model: %s", VOICE_WHISPER_MODEL)
                self._whisper_model = WhisperModel(
                    VOICE_WHISPER_MODEL,
                    device="cpu",
                    compute_type=VOICE_WHISPER_COMPUTE_TYPE,
                )

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as audio_file:
                with wave.open(audio_file.name, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(sample_width)
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(audio_bytes)

                segments, _ = self._whisper_model.transcribe(
                    audio_file.name,
                    language="en",
                    beam_size=5,
                    best_of=5,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    vad_filter=True,
                    vad_parameters={
                        "min_silence_duration_ms": 400,
                        "speech_pad_ms": 250,
                    },
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
                return text, None
        except Exception as exc:
            logger.exception("Whisper transcription failed")
            return "", f"Whisper transcription failed: {exc}"

    def _select_input_device(self, audio: pyaudio.PyAudio) -> tuple[Optional[int], dict]:
        if VOICE_INPUT_DEVICE_INDEX is not None:
            index = int(VOICE_INPUT_DEVICE_INDEX)
            return index, audio.get_device_info_by_index(index)

        default_input = audio.get_default_input_device_info()
        if not VOICE_PREFER_BUILTIN_MIC:
            return None, default_input

        preferred_terms = ("macbook", "built-in", "internal")
        for index in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(index)
            if info.get("maxInputChannels", 0) < 1:
                continue
            name = str(info.get("name", "")).lower()
            if any(term in name for term in preferred_terms):
                return index, info

        return None, default_input

    def _audio_levels(self, audio_bytes: bytes, sample_width: int) -> tuple[int, int]:
        if sample_width != 2 or not audio_bytes:
            return 0, 0
        samples = array.array("h")
        samples.frombytes(audio_bytes)
        if not samples:
            return 0, 0
        total = sum(sample * sample for sample in samples)
        rms = int((total / len(samples)) ** 0.5)
        peak = max(abs(sample) for sample in samples)
        return rms, peak
