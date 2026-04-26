import asyncio
import sys
import unittest
from types import ModuleType
from unittest.mock import MagicMock


import time as _time


class _FakeStream:
    """A fake PyAudio stream. Rate-limits reads so the capture loop
    behaves like a real microphone (~64ms per 1024-sample chunk at 16kHz)
    rather than spinning at full CPU speed and producing megabytes of audio.
    """

    def __init__(self, chunks, chunk_seconds=0.064):
        self._chunks = list(chunks)
        self._idx = 0
        self._chunk_seconds = chunk_seconds

    def read(self, _size, exception_on_overflow=False):
        _time.sleep(self._chunk_seconds)
        if self._idx >= len(self._chunks):
            return b"\x00\x00" * 1024
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk

    def stop_stream(self):
        pass

    def close(self):
        pass


class _FakePyAudio:
    def __init__(self, chunks):
        self._chunks = chunks

    def open(self, **_kwargs):
        return _FakeStream(self._chunks)

    def get_sample_size(self, _fmt):
        return 2

    def get_default_input_device_info(self):
        return {"index": 0, "name": "fake", "defaultSampleRate": 16000}

    def get_device_info_by_index(self, _idx):
        return {"index": 0, "name": "fake", "defaultSampleRate": 16000}

    def get_device_count(self):
        return 0

    def terminate(self):
        pass


def _install_fake_pyaudio_module(chunks):
    fake = ModuleType("pyaudio")
    fake.paInt16 = 8

    class _PA(_FakePyAudio):
        def __init__(self):
            super().__init__(chunks)

    fake.PyAudio = _PA
    sys.modules["pyaudio"] = fake
    fake_sr = ModuleType("speech_recognition")

    class _Rec:
        def recognize_sphinx(self, _data):
            return ""

    class _AD:
        def __init__(self, *_a, **_kw):
            pass

    class _UV(Exception):
        pass

    class _RE(Exception):
        pass

    fake_sr.Recognizer = _Rec
    fake_sr.AudioData = _AD
    fake_sr.UnknownValueError = _UV
    fake_sr.RequestError = _RE
    sys.modules["speech_recognition"] = fake_sr


def _make_speech_chunk(amplitude=2000, samples=1024):
    body = (amplitude.to_bytes(2, "little", signed=True)) * samples
    return body


def _make_silence_chunk(samples=1024):
    return b"\x00\x00" * samples


class TestVoiceAutoMode(unittest.IsolatedAsyncioTestCase):
    async def test_auto_capture_self_terminates_on_silence(self):
        # 6 chunks (~384ms) of speech then 24 chunks (~1.5s) of silence — the
        # capture loop should self-terminate within the silence window without
        # any voice_stop being sent.
        chunks = [_make_speech_chunk()] * 6 + [_make_silence_chunk()] * 24
        _install_fake_pyaudio_module(chunks)
        # Re-import voice with the patched pyaudio module
        for mod_name in ["voice"]:
            sys.modules.pop(mod_name, None)
        from bus import EventBus
        import voice

        bus = EventBus()
        events: list[tuple[str, dict]] = []

        async def record(name):
            async def handler(**kwargs):
                events.append((name, kwargs))

            return handler

        for name in ("voice_state", "voice_transcript", "voice_error"):
            bus.subscribe(name, await record(name))

        manager = voice.VoiceInputManager(bus)
        manager._transcribe_offline = MagicMock(return_value=("hello world", None))

        await bus.emit("voice_start", mode="auto")
        # Watchdog will finalize when capture loop exits naturally.
        for _ in range(60):
            await asyncio.sleep(0.05)
            if any(name == "voice_transcript" for name, _ in events):
                break

        names = [name for name, _ in events]
        self.assertIn("voice_state", names)
        self.assertIn("voice_transcript", names)

        transcript_event = next(p for n, p in events if n == "voice_transcript")
        self.assertEqual(transcript_event["text"], "hello world")

        states = [p for n, p in events if n == "voice_state"]
        listening_seq = [s["listening"] for s in states]
        self.assertEqual(listening_seq[0], True)
        self.assertEqual(listening_seq[-1], False)
        self.assertTrue(all(s.get("mode") == "auto" for s in states))

    async def test_manual_mode_does_not_self_terminate_on_silence(self):
        # Use a small number of chunks so audio_levels doesn't churn through
        # hundreds of KB of silence in pure Python during the test.
        chunks = [_make_silence_chunk()] * 16
        _install_fake_pyaudio_module(chunks)
        for mod_name in ["voice"]:
            sys.modules.pop(mod_name, None)
        from bus import EventBus
        import voice

        bus = EventBus()

        manager = voice.VoiceInputManager(bus)
        manager._transcribe_offline = MagicMock(return_value=("noop", None))

        await bus.emit("voice_start", mode="manual")
        await asyncio.sleep(0.2)
        async with manager._lock:
            still_listening = manager._is_listening
        self.assertTrue(
            still_listening,
            "manual mode must keep listening until voice_stop",
        )

        await bus.emit("voice_stop")
        for _ in range(40):
            await asyncio.sleep(0.05)
            async with manager._lock:
                stopped = not manager._is_listening
            if stopped:
                break
        self.assertTrue(stopped)


if __name__ == "__main__":
    unittest.main()
