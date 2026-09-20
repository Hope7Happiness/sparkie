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
    async def test_buffered_dual_input_drains_without_starving_participant_stt(self):
        from test_zoom_audio import packet
        with tempfile.TemporaryDirectory() as root:
            meeting = ZoomMacAudioMeeting(Path(root), Path(root) / 'unused')
            meeting.mixed_audio = True
            received, mixed = [], []
            class Ears:
                async def transcribe(self, frames):
                    self.on_ready()
                    async for item in frames:
                        received.append(item.pcm)
                        if len(received) % 32 == 0:
                            await asyncio.sleep(0)
                    yield TranscriptEvent('meeting', 'done', 0, 'all audio consumed')
            router = ParticipantEars(Ears)
            async def transcribe():
                return [e async for e in router.transcribe(meeting.participant_audio_stream())]
            async def foreground():
                async for item in meeting.audio():
                    mixed.append(item.pcm)
            meeting.reader = asyncio.StreamReader()
            meeting.reader_task = asyncio.create_task(meeting.receive())
            stt = asyncio.create_task(transcribe())
            fg = asyncio.create_task(foreground())
            count = 6000
            pcm = struct.pack('<h', 100) * 320
            meeting.reader.feed_data(b''.join(
                packet(b'A', pcm) + packet(b'U', struct.pack('!IQ', 10, i * 10) + pcm)
                for i in range(count)))
            try:
                async with asyncio.timeout(30):
                    while meeting.frames_received < count * 2 or len(mixed) < count:
                        if meeting.failure:
                            raise meeting.failure
                        if stt.done():
                            stt.result()
                        await asyncio.sleep(.001)
                meeting.input_finished = True
                meeting.participant_input_done.set()
                events = await asyncio.wait_for(stt, 5)
                self.assertEqual(received, [pcm] * count + [b'\0\0' * 16000])
                self.assertEqual(mixed, [pcm] * count)
                self.assertEqual([e.speaker_id for e in events], ['zoom:10'])
                self.assertIsNone(meeting.participant_failure)
                self.assertLess(meeting.participant_max_queued, 500)
            finally:
                stt.cancel()
                fg.cancel()
                await asyncio.gather(stt, fg, return_exceptions=True)
                await meeting.leave()

    async def test_realtime_splits_user_stt_from_mixed_foreground_and_preserves_capture_gating(self):
        from sparkie.realtime_zoom_audio import RealtimeZoomAudio
        from test_zoom_audio import packet
        with tempfile.TemporaryDirectory() as root:
            meeting = ZoomMacAudioMeeting(Path(root), Path(root) / 'unused')
            audio = RealtimeZoomAudio(meeting, on_event=lambda *args, **kwargs: None)
            self.assertTrue(meeting.participant_audio)
            self.assertTrue(meeting.mixed_audio)
            self.assertEqual(meeting.diagnostics()['input_mode'], 'mixed_and_per_participant')
            meeting.reader = asyncio.StreamReader()
            meeting.reader_task = asyncio.create_task(meeting.receive())
            pcm = b'\x01\0' * 320
            try:
                meeting.reader.feed_data(packet(b'A', pcm))
                frame = await asyncio.wait_for(meeting.queue.get(), 2)
                self.assertEqual(frame.pcm, pcm)
                self.assertFalse(frame.gated)
                self.assertIsNone(frame.speaker_id)
                audio.append_output('reply', b'\x01\0' * 2400)
                meeting.reader.feed_data(packet(b'A', pcm))
                frame = await asyncio.wait_for(meeting.queue.get(), 2)
                self.assertTrue(frame.gated)
                self.assertEqual(frame.pcm, bytes(len(pcm)))
                meeting.reader.feed_data(packet(b'U', struct.pack('!IQ', 10, 1200) + pcm))
                user_frame = await asyncio.wait_for(meeting.participant_queue.get(), 2)
                self.assertEqual(user_frame.pcm, pcm)
                self.assertEqual(user_frame.speaker_id, 'zoom:10')
                self.assertEqual(meeting.queue.qsize(), 0)
            finally:
                await meeting.leave()

    async def test_participant_overflow_does_not_stop_mixed_input(self):
        from sparkie.realtime_zoom_audio import RealtimeZoomAudio
        from test_zoom_audio import packet
        with tempfile.TemporaryDirectory() as root:
            meeting = ZoomMacAudioMeeting(Path(root), Path(root) / 'unused')
            RealtimeZoomAudio(meeting, on_event=lambda *a, **kw: None)
            meeting.participant_queue = asyncio.Queue(maxsize=1)
            meeting.reader = asyncio.StreamReader()
            meeting.reader_task = asyncio.create_task(meeting.receive())
            pcm = b'\x01\0' * 320
            meeting.reader.feed_data(packet(b'U', struct.pack('!IQ', 10, 0) + pcm) * 2 + packet(b'A', pcm))
            try:
                mixed = await asyncio.wait_for(meeting.queue.get(), 2)
                self.assertEqual(mixed.pcm, pcm)
                self.assertIsNone(meeting.failure)
                self.assertFalse(meeting.participant_accepting)
                with self.assertRaisesRegex(ProviderError, 'queue full'):
                    await anext(meeting.participant_audio_stream())
            finally:
                await meeting.leave()

    async def test_old_native_binary_cannot_silently_start_without_dual_streams(self):
        from unittest.mock import AsyncMock, Mock, patch
        from test_zoom_audio import packet
        with tempfile.TemporaryDirectory() as root:
            meeting = ZoomMacAudioMeeting(Path(root), Path(root) / 'unused')
            meeting.port, meeting._token = 123, 'fixture'
            for handshake, valid in [(b'cancel-v1', False), (meeting.handshake, True)]:
                reader = asyncio.StreamReader()
                reader.feed_data(packet(b'H', handshake))
                writer = Mock(drain=AsyncMock())
                meeting.failure = None
                with patch('asyncio.open_connection', new=AsyncMock(return_value=(reader, writer))):
                    if valid:
                        await meeting.connect()
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'rebuild'):
                            await meeting.connect()
                meeting.writer = None

    async def test_input_end_drains_user_frames_and_ignores_packets_during_final_flush(self):
        with tempfile.TemporaryDirectory() as root:
            meeting = ZoomMacAudioMeeting(Path(root), Path(root) / 'unused')
            meeting.mixed_audio = True
            meeting.enqueue_frame(frame('zoom:10', 0))
            meeting.input_finished = True
            meeting.participant_input_done.set()
            for i in range(1100):
                meeting.enqueue_frame(AudioFrame(i, b'\0\0'))
                meeting.enqueue_frame(frame('zoom:20', 10))
            records = [f async for f in meeting.participant_audio_stream()]
            self.assertEqual([f.speaker_id for f in records], ['zoom:10'])
            self.assertTrue(meeting.queue.empty())
            self.assertIsNone(meeting.participant_failure)

    async def test_wire_demultiplexing_metadata_heartbeat_and_old_binary_rejection(self):
        import json
        from test_zoom_audio import packet
        with tempfile.TemporaryDirectory() as root:
            meeting = ZoomMacAudioMeeting(Path(root), Path(root) / 'unused')
            meeting.reader = asyncio.StreamReader()
            users = [{'user_id': 10, 'name': '张三', 'is_self': False},
                     {'user_id': 99, 'name': 'Sparkie', 'is_self': True}]
            meeting.reader.feed_data(packet(b'J', json.dumps(users).encode()) + packet(b'R') +
                packet(b'U', struct.pack('!IQ', 10, 1200) + b'\x01\0' * 320))
            meeting.reader_task = asyncio.create_task(meeting.receive())
            try:
                received = await asyncio.wait_for(meeting.queue.get(), 2)
                self.assertEqual((received.speaker_id, received.timestamp_ms), ('zoom:10', 1200))
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
