import asyncio
import struct
import tempfile
import unittest
from pathlib import Path

from sparkie.zoom_audio import ZoomAudioMeeting


def packet(kind, data=b''):
    return kind + struct.pack('!I', len(data)) + data


class ZoomVoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.meeting = ZoomAudioMeeting(Path(self.temp.name), max_seconds=.1)
        self.meeting.reader = asyncio.StreamReader()
        self.events = []
        self.meeting.on_event = lambda kind, **kw: self.events.append((kind, kw))

    async def asyncTearDown(self):
        await self.meeting.leave()
        self.temp.cleanup()

    async def test_audio_and_mic_readiness_are_separate(self):
        self.meeting.reader.feed_data(packet(b'M') + packet(b'A', b'\x01\x00' * 320))
        self.meeting.reader_task = asyncio.create_task(self.meeting.receive())
        await asyncio.sleep(.01)
        self.assertTrue(self.meeting.mic_ready.is_set())
        self.assertTrue(self.meeting.audio_ready.is_set())
        frame = self.meeting.queue.get_nowait()
        self.assertEqual(frame.pcm, b'\x01\x00' * 320)
        self.assertEqual(frame.sample_rate, 32000)
        self.assertIsNone(self.meeting.last_playback_started_at)

    async def test_disconnect_is_failure_not_silent_end(self):
        self.meeting.reader.feed_eof()
        await self.meeting.receive()
        self.assertIsInstance(self.meeting.failure, asyncio.IncompleteReadError)
        with self.assertRaises(asyncio.IncompleteReadError):
            async for _ in self.meeting.audio():
                pass

    async def test_backpressure_fails_without_dropping_frames(self):
        self.meeting.queue = asyncio.Queue(maxsize=1)
        self.meeting.reader.feed_data(packet(b'A', b'\0\0') * 2)
        await self.meeting.receive()
        self.assertIsInstance(self.meeting.failure, asyncio.QueueFull)

    async def test_malformed_frame_rejected(self):
        self.meeting.reader.feed_data(packet(b'A', b'x'))
        await self.meeting.receive()
        self.assertIsInstance(self.meeting.failure, RuntimeError)

    async def test_oversized_packet_rejected_before_allocation(self):
        self.meeting.reader.feed_data(b'A' + struct.pack('!I', 10000000))
        with self.assertRaises(RuntimeError):
            await self.meeting.read_packet()

    async def test_playback_waits_for_matching_completed_id(self):
        sent = []
        async def send(kind, data=b''):
            sent.append((kind, data))
        self.meeting.send_packet = send
        self.meeting.mic_ready.set()
        play = asyncio.create_task(self.meeting.play_audio(b'\0\0' * 320, 32000))
        await asyncio.sleep(0)
        self.meeting.reader_task = asyncio.create_task(self.meeting.receive())
        self.meeting.reader.feed_data(packet(b'S', struct.pack('!I', 1)) + packet(b'D', struct.pack('!I', 2)))
        await asyncio.sleep(.01)
        self.assertFalse(play.done())
        self.meeting.reader.feed_data(packet(b'D', struct.pack('!I', 1)))
        await asyncio.wait_for(play, 1)
        self.assertEqual(sent[0], (b'P', struct.pack('!I', 1) + b'\0\0' * 320))
        self.assertIn('zoom_playback_submitted', [x[0] for x in self.events])

    async def test_muted_microphone_rejects_playback(self):
        with self.assertRaises(RuntimeError):
            await self.meeting.play_audio(b'\0\0' * 320, 32000)

    async def test_cancel_sends_stop_and_cleans_pending_future(self):
        sent = []
        async def send(kind, data=b''):
            sent.append(kind)
        async def stop():
            await send(b'C')
        self.meeting.send_packet = send
        self.meeting.stop_speaking = stop
        self.meeting.mic_ready.set()
        play = asyncio.create_task(self.meeting.play_audio(b'\0\0' * 320, 32000))
        await asyncio.sleep(0)
        play.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await play
        self.assertEqual(sent, [b'P', b'C'])
        self.assertEqual(self.meeting.playbacks, {})

    async def test_mid_playback_mute_fails_pending_reply(self):
        future = asyncio.get_running_loop().create_future()
        self.meeting.playbacks[1] = future
        self.meeting.reader.feed_data(packet(b'N'))
        self.meeting.reader_task = asyncio.create_task(self.meeting.receive())
        with self.assertRaisesRegex(RuntimeError, 'muted during playback'):
            await asyncio.wait_for(future, 1)

    async def test_leave_removes_only_owned_container_and_private_files(self):
        calls = []
        async def docker(*args):
            calls.append(args)
            return ''
        self.meeting.docker = docker
        self.meeting._owns_container = True
        for name in ('config.txt', 'bridge-token'):
            (self.meeting.runtime / name).write_text('test secret')
        await self.meeting.leave()
        self.assertIn(('kill', '--signal', 'SIGINT', self.meeting.name), calls)
        self.assertIn(('rm', '-f', self.meeting.name), calls)
        self.assertFalse((self.meeting.runtime / 'config.txt').exists())
        self.assertFalse((self.meeting.runtime / 'bridge-token').exists())
        count = len(calls)
        await self.meeting.leave()
        self.assertEqual(len(calls), count)

    async def test_failed_start_with_no_container_still_cleans_secrets(self):
        async def docker(*args):
            if args[0] != 'ps':
                raise RuntimeError('Docker command failed')
            return ''
        self.meeting.docker = docker
        self.meeting._owns_container = True
        (self.meeting.runtime / 'bridge-token').write_text('test secret')
        await self.meeting.leave()
        self.assertFalse((self.meeting.runtime / 'bridge-token').exists())
