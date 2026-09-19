import asyncio
import json
import os
import stat
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sparkie.zoom_audio import ZoomAudioMeeting, ZoomMacAudioMeeting


def packet(kind, data=b''):
    return kind + struct.pack('!I', len(data)) + data


class ZoomVoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_error_resolves_playback_and_preserves_safe_details(self):
        from sparkie.providers import failure_details
        from sparkie.zoom_errors import ZoomBridgeError
        self.meeting.send_packet = AsyncMock()
        self.meeting.mic_ready.set()
        play = asyncio.create_task(self.meeting.play_audio(bytes(6400), 32000))
        await asyncio.sleep(0)
        detail = {'version': 1, 'reason': 'sdk_send_failed', 'sdk_result': 20,
                  'playback_id': 1, 'frame_index': 3, 'message': 'private secret'}
        self.meeting.reader.feed_data(packet(b'S', struct.pack('!I', 1)) +
                                      packet(b'E', json.dumps(detail).encode()))
        await self.meeting.receive()
        with self.assertRaises(ZoomBridgeError) as caught:
            await asyncio.wait_for(play, 1)
        fields = failure_details(caught.exception)
        self.assertEqual(fields['provider'], 'zoom')
        self.assertEqual(fields['reason'], 'sdk_send_failed')
        self.assertEqual(fields['sdk_result'], 20)
        self.assertEqual(fields['frame_index'], 3)
        self.assertTrue(self.meeting.stopped.is_set())
        self.assertEqual(self.meeting.playbacks, {})
        self.assertNotIn('private', json.dumps(self.events) + json.dumps(fields))

    async def test_native_error_legacy_and_untrusted_payloads(self):
        from sparkie.zoom_errors import ZoomBridgeError
        from sparkie.providers import failure_details
        for payload, reason in ZoomBridgeError.LEGACY.items():
            self.assertEqual(failure_details(ZoomBridgeError(payload))['reason'], reason)
        for payload in (b'secret', b'[]', b'null', b'\xff', b'x' * 513,
                        b'{"version":1,"reason":["secret"]}',
                        b'{"version":1,"reason":"secret","sdk_result":20}'):
            fields = failure_details(ZoomBridgeError(payload))
            self.assertEqual(fields['reason'], 'unknown_native_error')
            self.assertNotIn('secret', json.dumps(fields))
        fields = failure_details(ZoomBridgeError(
            b'{"version":1,"reason":"sdk_send_failed","sdk_result":true,"frame_index":"secret"}'))
        self.assertNotIn('sdk_result', fields)
        self.assertNotIn('frame_index', fields)

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

    async def test_stt_connection_startup_has_extra_bounded_buffer(self):
        self.meeting.reader.feed_data(packet(b'A', b'\0\0') * 300 + packet(b'M'))
        self.meeting.reader_task = asyncio.create_task(self.meeting.receive())
        await asyncio.wait_for(self.meeting.mic_ready.wait(), 3)
        self.assertIsNone(self.meeting.failure)
        self.assertEqual(self.meeting.queue.qsize(), 300)
        self.assertEqual(self.meeting.queue.maxsize, 1000)

    async def test_sustained_backlog_warns_then_fails_at_bound(self):
        self.meeting.reader.feed_data(packet(b'A', b'\0\0') * 1001)
        await self.meeting.receive()
        self.assertIsInstance(self.meeting.failure, asyncio.QueueFull)
        warnings = [kw for kind, kw in self.events if kind == 'audio_warning']
        self.assertEqual(warnings, [{'reason': 'zoom_input_backlog', 'queued_frames': 250}])

    async def test_startup_backlog_drains_without_losing_audio(self):
        from sparkie.audio import AudioFrame
        self.meeting.max_seconds = 60
        for i in range(300):
            self.meeting.queue.put_nowait(AudioFrame(i, b'\0\0'))
        self.meeting._backlogged = True
        stream = self.meeting.audio()
        frames = [await anext(stream) for _ in range(300)]
        self.assertEqual([frame.sequence for frame in frames], list(range(300)))
        self.assertFalse(self.meeting._backlogged)
        self.assertIn(('zoom_input_recovered', {}), self.events)
        await stream.aclose()

    async def test_transport_burst_reaches_stt_without_overflow_or_lost_frames(self):
        import json
        from sparkie.providers import DeepgramEars

        class Socket:
            def __init__(self):
                self.sent = []
                self.closed = asyncio.Event()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def send(self, payload):
                if isinstance(payload, bytes):
                    self.sent.append(payload)
                elif json.loads(payload)["type"] == "CloseStream":
                    self.closed.set()
            def __aiter__(self):
                return self
            async def __anext__(self):
                await self.closed.wait()
                raise StopAsyncIteration

        socket = Socket()
        count = 4000
        self.meeting.max_seconds = 60
        expected = [struct.pack('<h', i) * 320 for i in range(count)]
        self.meeting.reader_task = asyncio.create_task(self.meeting.receive())
        async def frames():
            async for frame in self.meeting.audio():
                yield frame
                if frame.sequence == count:
                    return
        ears = DeepgramEars('test', 'burst', connector=lambda *args: socket)
        async def transcribe():
            return [event async for event in ears.transcribe(frames())]
        consumer = asyncio.create_task(transcribe())
        try:
            # Let the consumer block awaiting its first audio before TCP delivers a burst.
            await asyncio.sleep(.01)
            self.meeting.reader.feed_data(b''.join(packet(b'A', pcm) for pcm in expected))
            await asyncio.wait_for(consumer, 10)
            self.assertIsNone(self.meeting.failure)
            self.assertEqual(socket.sent, expected)
        finally:
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.terminated = False

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    async def wait(self):
        return self.returncode


class ZoomMacVoiceTests(unittest.IsolatedAsyncioTestCase):
    ENV = {'ZOOM_CLIENT_ID': 'client-test', 'ZOOM_CLIENT_SECRET': 'secret-value',
           'ZOOM_MEETING_ID': '123 4567-8901', 'ZOOM_MEETING_PASSWORD': '001234',
           'OPENAI_API_KEY': 'other-secret'}

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.binary = Path(self.temp.name) / 'SparkieZoom'
        self.binary.touch()
        self.meeting = ZoomMacAudioMeeting(Path(self.temp.name) / 'run', self.binary, max_seconds=.1)

    async def asyncTearDown(self):
        await self.meeting.leave()
        self.temp.cleanup()

    async def test_launch_writes_voice_config_and_excludes_provider_secrets(self):
        with patch.dict(os.environ, self.ENV, clear=True), \
             patch('asyncio.create_subprocess_exec', new=AsyncMock(return_value=FakeProcess())) as spawn:
            await self.meeting.launch()
        config_path = self.meeting.runtime / 'config.json'
        config = json.loads(config_path.read_text())
        self.assertIs(config['voice'], True)
        self.assertEqual(config['bridge_token'], self.meeting._token)
        self.assertEqual(config['bridge_port'], self.meeting.port)
        self.assertEqual(config['meeting_number'], '12345678901')
        self.assertNotIn('secret-value', config_path.read_text())
        self.assertEqual(stat.S_IMODE(config_path.stat().st_mode), 0o600)
        env = spawn.call_args.kwargs['env']
        self.assertNotIn('ZOOM_CLIENT_SECRET', env)
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertTrue(env['SPARKIE_ZOOM_CONFIG'].endswith('config.json'))

    async def test_missing_binary_explains_build_step(self):
        meeting = ZoomMacAudioMeeting(Path(self.temp.name) / 'x', Path(self.temp.name) / 'missing')
        with self.assertRaisesRegex(ValueError, 'build --platform macos'):
            await meeting.launch()

    async def test_exited_receiver_fails_connect_fast(self):
        self.meeting.process = FakeProcess(returncode=1)
        self.assertIsInstance(self.meeting.launch_failure(), RuntimeError)

    async def test_leave_terminates_process_and_removes_config(self):
        process = FakeProcess()
        self.meeting.process = process
        self.meeting.runtime.mkdir(parents=True)
        (self.meeting.runtime / 'config.json').write_text('secret')
        await self.meeting.leave()
        self.assertTrue(process.terminated)
        self.assertFalse((self.meeting.runtime / 'config.json').exists())
        await self.meeting.leave()
