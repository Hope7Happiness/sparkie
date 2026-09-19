import asyncio
import queue
import time
import unittest
from types import SimpleNamespace

from sparkie.local_audio import LocalAudioMeeting
from sparkie.providers import ProviderError


def timing():
    return SimpleNamespace(inputBufferAdcTime=9.99, currentTime=10, outputBufferDacTime=10.01)


STATUS = SimpleNamespace(input_overflow=False, output_underflow=False)


class LocalAudioTests(unittest.IsolatedAsyncioTestCase):
    def meeting(self, mode="speaker"):
        meeting = LocalAudioMeeting(echo_mode=mode)
        meeting._loop = asyncio.get_running_loop()
        meeting._stream = SimpleNamespace(active=True)
        return meeting

    async def test_microphone_samples_and_origin_are_preserved(self):
        meeting = self.meeting()
        pcm = b"\x01\x00" * 640
        output = bytearray(1280)
        before = time.monotonic()
        meeting._callback(pcm, output, 640, timing(), STATUS)
        frame = meeting._queue.get_nowait()
        self.assertEqual(frame.pcm, pcm)
        self.assertEqual(frame.sequence, 0)
        self.assertEqual(bytes(output), b"\0" * 1280)
        self.assertLess(abs(meeting.audio_origin - before), .1)

    async def test_speaker_gate_covers_playback_and_echo_tail(self):
        meeting = self.meeting()
        reply = b"\x02\x00" * 320
        task = asyncio.create_task(meeting.play_audio(reply, 32000))
        await asyncio.sleep(0)
        output = bytearray(1280)
        meeting._callback(b"\x01\x00" * 640, output, 640, timing(), STATUS)
        self.assertEqual(output[:640], reply)
        self.assertEqual(output[640:], b"\0" * 640)
        self.assertEqual(meeting._queue.get_nowait().pcm, b"\0" * 1280)
        # Last reply block has finished, but the input gate remains for speaker echo.
        meeting._callback(b"\x01\x00" * 640, bytearray(1280), 640, timing(), STATUS)
        self.assertEqual(meeting._queue.get_nowait().pcm, b"\0" * 1280)
        self.assertEqual(meeting.gated_samples, 1280)
        await task
        self.assertIsNotNone(meeting.last_playback_started_at)
        meeting._gate_until = 0
        meeting._callback(b"\x01\x00" * 640, bytearray(1280), 640, timing(), STATUS)
        self.assertEqual(meeting._queue.get_nowait().pcm, b"\x01\x00" * 640)

    async def test_headphones_keep_input_during_playback(self):
        meeting = self.meeting("headphones")
        task = asyncio.create_task(meeting.play_audio(b"\x02\x00" * 320, 32000))
        await asyncio.sleep(0)
        pcm = b"\x01\x00" * 640
        meeting._callback(pcm, bytearray(1280), 640, timing(), STATUS)
        self.assertEqual(meeting._queue.get_nowait().pcm, pcm)
        self.assertEqual(meeting.gated_samples, 0)
        await task

    async def test_cancellation_zeros_next_output_buffer(self):
        meeting = self.meeting()
        task = asyncio.create_task(meeting.play_audio(b"\x02\x00" * 6400, 32000))
        await asyncio.sleep(0)
        await meeting.stop_speaking()
        output = bytearray(1280)
        meeting._callback(b"\0" * 1280, output, 640, timing(), STATUS)
        await task
        self.assertEqual(output, b"\0" * 1280)
        self.assertIsNone(meeting._playback)

    async def test_bounded_capture_queue_fails_instead_of_silent_sample_loss(self):
        meeting = self.meeting()
        meeting._queue = queue.Queue(maxsize=1)
        for _ in range(2):
            meeting._callback(b"\0" * 1280, bytearray(1280), 640, timing(), STATUS)
        with self.assertRaisesRegex(ProviderError, "queue full"):
            await anext(meeting.audio())

    async def test_device_input_overflow_is_explicit(self):
        meeting = self.meeting()
        status = SimpleNamespace(input_overflow=True, output_underflow=False)
        meeting._callback(b"\0" * 1280, bytearray(1280), 640, timing(), status)
        self.assertEqual(meeting.input_overflows, 1)
        self.assertFalse(meeting.timing_reliable)
        self.assertIsNone(meeting._error)
        for _ in range(4):
            meeting._callback(b"\0" * 1280, bytearray(1280), 640, timing(), status)
        with self.assertRaisesRegex(ProviderError, "overflow"):
            await anext(meeting.audio())

    async def test_failed_open_closes_partial_stream(self):
        stream = SimpleNamespace(closed=False)
        def start():
            raise RuntimeError("permission denied")
        def close():
            stream.closed = True
        stream.start, stream.close = start, close
        driver = SimpleNamespace(check_input_settings=lambda **k: None, check_output_settings=lambda **k: None,
                                 RawStream=lambda **k: stream)
        meeting = LocalAudioMeeting(driver=driver)
        with self.assertRaisesRegex(ProviderError, "microphone permission"):
            await meeting.join()
        self.assertTrue(stream.closed)
        self.assertIsNone(meeting._stream)

    async def test_stalled_active_device_fails_instead_of_listening_forever(self):
        meeting = self.meeting()
        meeting._last_capture_at = time.monotonic() - 4
        events = []
        meeting.on_event = lambda kind, **fields: events.append((kind, fields))
        with self.assertRaisesRegex(ProviderError, 'stopped delivering'):
            await anext(meeting.audio())
        self.assertIn(('audio_failed', {'reason': 'capture_stalled', 'timing_reliable': False}), events)
        self.assertEqual(events[-1][0], 'audio_input_ended')

    async def test_repeated_overflow_emits_fatal_event_before_unwinding(self):
        meeting = self.meeting()
        events = []
        meeting.on_event = lambda kind, **fields: events.append((kind, fields))
        status = SimpleNamespace(input_overflow=True, output_underflow=False)
        for _ in range(5):
            meeting._callback(b'\0' * 1280, bytearray(1280), 640, timing(), status)
        with self.assertRaises(ProviderError):
            await anext(meeting.audio())
        self.assertEqual(events[0][0], 'audio_failed')
        self.assertEqual(events[0][1]['reason'], 'capture_overrun')

    async def test_metering_does_not_run_inside_realtime_callback(self):
        meeting = self.meeting()
        events = []
        meeting.on_event = lambda kind, **fields: events.append((kind, fields))
        meeting._callback(b'\xff\x1f' * 640, bytearray(1280), 640, timing(), STATUS)
        self.assertEqual(meeting.input_peak, 0)
        stream = meeting.audio()
        frame = await anext(stream)
        self.assertEqual(frame.pcm[:2], b'\xff\x1f')
        self.assertGreater(meeting.input_peak, 0)
        self.assertTrue(any(kind == 'audio_level' for kind, _ in events))
        await stream.aclose()
