import asyncio
import struct
import tempfile
import unittest
from pathlib import Path

from sparkie.audio import AudioFrame
from sparkie.contracts import TranscriptEvent
from sparkie.participant_stt import ParticipantEars
from sparkie.providers import ProviderError
from sparkie.zoom_audio import ZoomMacAudioMeeting


def frame(user, start, value=1):
    return AudioFrame(0, struct.pack('<h', value) * 320, speaker_id=user, timestamp_ms=start)


class ParticipantTests(unittest.IsolatedAsyncioTestCase):
    def factory(self, *, fail=False, wait=None):
        self.received, self.closed = [], []
        parent = self
        class Ears:
            async def transcribe(self, frames):
                packets = []
                parent.received.append(packets)
                try:
                    if wait:
                        await wait.wait()
                    if fail:
                        raise ProviderError('fixture failure')
                    self.on_ready()
                    async for packet in frames:
                        packets.append(packet.pcm)
                    yield TranscriptEvent('meeting', 'dg-1', 10, 'test words')
                finally:
                    parent.closed.append(True)
        return Ears

    async def test_simultaneous_users_same_name_remain_separate_and_share_clock(self):
        router = ParticipantEars(self.factory(), speaker_name=lambda _: 'Same name')
        async def frames():
            yield frame('zoom:10', 1000, 100)
            yield frame('zoom:20', 1000, 200)
            yield frame('zoom:10', 1100, 101)
            yield frame('zoom:20', 1100, 201)
        events = [e async for e in router.transcribe(frames())]
        self.assertEqual({e.speaker_id for e in events}, {'zoom:10', 'zoom:20'})
        self.assertEqual({e.speaker for e in events}, {'Same name'})
        self.assertEqual([e.timestamp_ms for e in events], [1010, 1010])
        self.assertEqual(len({e.event_id for e in events}), 2)
        self.assertEqual(len(self.closed), 2)
        for packets, values in zip(self.received, [(100, 101), (200, 201)]):
            self.assertEqual(packets[0], struct.pack('<h', values[0]) * 320)
            self.assertEqual(packets[1], b'\0\0' * (90 * 32))
            self.assertEqual(packets[2], struct.pack('<h', values[1]) * 320)

    async def test_long_pause_reopens_without_compressing_time_or_duplicate_ids(self):
        router = ParticipantEars(self.factory())
        async def frames():
            yield frame('zoom:10', 500)
            yield frame('zoom:10', 10500)
        events = [e async for e in router.transcribe(frames())]
        self.assertEqual(sorted(e.timestamp_ms for e in events), [510, 10510])
        self.assertEqual(len({e.event_id for e in events}), 2)
        self.assertEqual(len(self.received), 2)

    async def test_silence_and_self_do_not_open_connections(self):
        router = ParticipantEars(self.factory(), is_self=lambda ident: ident == 'zoom:1')
        async def frames():
            yield frame('zoom:1', 0)
            for i in range(100):
                yield frame(f'zoom:{i + 2}', 0, 0)
        self.assertEqual([e async for e in router.transcribe(frames())], [])
        self.assertEqual(self.received, [])

    async def test_idle_user_flushes_before_meeting_ends(self):
        done = asyncio.Event()
        router = ParticipantEars(self.factory(), idle_seconds=.02)
        async def frames():
            yield frame('zoom:2', 100)
            await done.wait()
        stream = router.transcribe(frames())
        try:
            async with asyncio.timeout(2):
                event = await anext(stream)
            self.assertEqual(event.speaker_id, 'zoom:2')
            self.assertEqual(len(self.closed), 1)
        finally:
            done.set()
            await stream.aclose()

    async def test_provider_failure_and_cancellation_close_all_streams(self):
        router = ParticipantEars(self.factory(fail=True))
        async def frames():
            yield frame('zoom:2', 0)
            await asyncio.Event().wait()
        with self.assertRaisesRegex(ProviderError, 'fixture failure'):
            async for _ in router.transcribe(frames()): pass
        self.assertEqual(len(self.closed), 1)
        router = ParticipantEars(self.factory())
        async def consume():
            return [e async for e in router.transcribe(frames())]
        task = asyncio.create_task(consume())
        async with asyncio.timeout(2):
            while not self.received:
                await asyncio.sleep(.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(len(self.closed), 1)

    async def test_concurrency_and_backlog_fail_explicitly(self):
        async def users():
            yield frame('zoom:2', 0)
            yield frame('zoom:3', 0)
        router = ParticipantEars(self.factory(wait=asyncio.Event()), max_streams=1)
        with self.assertRaisesRegex(ProviderError, 'concurrency limit'):
            async for _ in router.transcribe(users()): pass
        async def burst():
            for i in range(3): yield frame('zoom:2', i * 10)
        router = ParticipantEars(self.factory(wait=asyncio.Event()), queue_frames=1)
        with self.assertRaises(asyncio.QueueFull):
            async for _ in router.transcribe(burst()): pass

    async def test_missing_identity_fails_instead_of_mixing(self):
        router = ParticipantEars(self.factory())
        async def frames(): yield AudioFrame(0, b'\0\0')
        with self.assertRaisesRegex(ProviderError, 'metadata'):
            async for _ in router.transcribe(frames()): pass


class MacPacketTests(unittest.IsolatedAsyncioTestCase):
    async def test_realtime_mixed_mode_keeps_capture_gate_and_rejects_user_packets(self):
        from test_zoom_audio import packet
        with tempfile.TemporaryDirectory() as root:
            meeting = ZoomMacAudioMeeting(Path(root), Path(root) / 'unused', per_participant=False)
            meeting.input_gate = lambda: True
            meeting.reader = asyncio.StreamReader()
            meeting.reader.feed_data(packet(b'A', b'\x01\0' * 320))
            meeting.reader_task = asyncio.create_task(meeting.receive())
            try:
                received = await asyncio.wait_for(meeting.queue.get(), 2)
                self.assertIsNone(received.speaker_id)
                self.assertTrue(received.gated)
                self.assertEqual(received.pcm, b'\0\0' * 320)
                self.assertEqual(meeting.diagnostics()['input_mode'], 'mixed')
                with self.assertRaises(RuntimeError):
                    meeting.decode_audio(b'U', struct.pack('!IQ', 10, 1200) + b'\x01\0')
            finally:
                await meeting.leave()

    async def test_wire_demultiplexing_metadata_heartbeat_and_old_binary_rejection(self):
        import json
        from test_zoom_audio import packet
        with tempfile.TemporaryDirectory() as root:
            meeting = ZoomMacAudioMeeting(Path(root), Path(root) / 'unused')
            meeting.input_gate = lambda: True  # Per-user speech stays live during playback.
            meeting.reader = asyncio.StreamReader()
            users = [{'user_id': 10, 'name': '张三', 'is_self': False},
                     {'user_id': 99, 'name': 'Sparkie', 'is_self': True}]
            meeting.reader.feed_data(packet(b'J', json.dumps(users).encode()) + packet(b'R') +
                packet(b'U', struct.pack('!IQ', 10, 1200) + b'\x01\0' * 320))
            meeting.reader_task = asyncio.create_task(meeting.receive())
            try:
                received = await asyncio.wait_for(meeting.queue.get(), 2)
                self.assertEqual((received.speaker_id, received.timestamp_ms), ('zoom:10', 1200))
                self.assertFalse(received.gated)
                self.assertEqual(received.pcm, b'\x01\0' * 320)
                self.assertEqual(meeting.speaker_name('zoom:10'), '张三')
                self.assertTrue(meeting.is_self('zoom:99'))
                self.assertTrue(meeting.audio_ready.is_set())
                self.assertEqual(meeting.queue.qsize(), 0)
                for payload in [b'', struct.pack('!IQ', 0, 0) + b'xx', b'x' * 13]:
                    with self.assertRaises(RuntimeError): meeting.decode_audio(b'U', payload)
                with self.assertRaisesRegex(RuntimeError, 'rebuild'):
                    meeting.decode_audio(b'A', b'\0\0')
                self.assertEqual(meeting.diagnostics()['echo_mode'], 'exclude_sdk_self_track')
            finally:
                await meeting.leave()
