"""Offline reproduction of native Connecting stall; no SDK/network initialization."""
import asyncio
import json
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from sparkie.providers import failure_details
from sparkie.zoom_audio import ZoomAudioMeeting, ZoomMacAudioMeeting
from sparkie.zoom_join import NativeJoinProgress, ZoomJoinError
from test_zoom_audio import FakeProcess, packet


class JoinTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.log = self.path / 'sdk.log'
        self.log.write_text('')
        self.events = []
        self.meeting = ZoomMacAudioMeeting(self.path, self.path / 'unused', join_timeout=.015)
        self.meeting.on_event = lambda kind, **fields: self.events.append((kind, fields))
        self.process = FakeProcess()
        async def launch():
            self.meeting.process = self.process
            (self.path / 'config.json').write_text('private')
        self.meeting.launch = launch
        self.meeting.connect = AsyncMock()
        async def receive(): await asyncio.Future()
        self.meeting.receive = receive
        self.addAsyncCleanup(self.meeting.leave)

    def write(self, lines):
        self.log.write_bytes(bytes([10]).join(line.encode() for line in lines) + bytes([10]))

    def startup_packets(self):
        self.meeting.mixed_audio = True
        self.meeting.reader = asyncio.StreamReader()
        self.meeting.receive = ZoomAudioMeeting.receive.__get__(self.meeting)
        pcm = b'\x01\x00' * 320
        # Reproduce more than the entire 1000-frame mix buffer while U runs too.
        self.meeting.reader.feed_data((packet(b'A', pcm) +
            packet(b'U', struct.pack('!IQ', 7, 0) + pcm)) * 1100)
        self.write(['MEETING_STATUS state=3 error=101 reason=0'])
        return pcm

    async def test_missing_microphone_reports_readiness_timeout_not_queuefull(self):
        self.startup_packets()
        self.meeting.join_timeout = .2
        with self.assertRaises(ZoomJoinError) as caught:
            await self.meeting.join()
        fields = failure_details(caught.exception)
        self.assertEqual(fields['reason'], 'audio_readiness_timeout')
        self.assertTrue(fields['audio_ready'])
        self.assertFalse(fields['microphone_ready'])
        self.assertEqual(self.meeting.startup_frames_discarded, 2200)
        self.assertEqual(self.meeting.max_queued_frames, 0)
        self.assertTrue(self.meeting.participant_queue.empty())
        self.assertTrue(self.process.terminated)
        self.assertEqual(sum(k == 'zoom_startup_audio_discarded' for k, _ in self.events), 1)
        self.assertFalse(any(k == 'audio_failed' for k, _ in self.events))

    async def test_delayed_microphone_starts_fresh_mix_and_participant_input(self):
        pcm = self.startup_packets()
        self.meeting.join_timeout = 1
        joining = asyncio.create_task(self.meeting.join())
        try:
            async with asyncio.timeout(1):
                while self.meeting.frames_received < 2200:
                    await asyncio.sleep(.001)
            self.assertFalse(joining.done())
            self.assertTrue(self.meeting.queue.empty())
            self.assertTrue(self.meeting.participant_queue.empty())
            self.meeting.reader.feed_data(packet(b'M'))
            await joining
            self.meeting.reader.feed_data(packet(b'A', pcm) +
                packet(b'U', struct.pack('!IQ', 7, 11000) + pcm))
            mixed = await asyncio.wait_for(self.meeting.queue.get(), 1)
            user = await asyncio.wait_for(self.meeting.participant_queue.get(), 1)
            self.assertEqual(mixed.pcm, pcm)
            self.assertIsNone(mixed.speaker_id)
            self.assertEqual(user.speaker_id, 'zoom:7')
            self.assertEqual(user.timestamp_ms, 11000)
            self.assertIsNone(self.meeting.failure)
        finally:
            joining.cancel()
            await asyncio.gather(joining, return_exceptions=True)

    async def test_exact_connecting_stall_is_bounded_classified_and_cleaned(self):
        self.write(['SDK_INIT result=0', 'SDK_AUTH_RESULT result=0', 'JOIN_REQUEST result=0',
                    'MEETING_STATUS state=1 error=101 reason=0'])
        with self.assertRaises(ZoomJoinError) as caught:
            await self.meeting.join()
        fields = failure_details(caught.exception)
        self.assertEqual(fields['reason'], 'connecting_timeout')
        self.assertEqual((fields['meeting_state'], fields['meeting_error'], fields['meeting_end_reason']), (1, 101, 0))
        self.assertFalse(fields['audio_ready'])
        self.assertIn('network/VPN', fields['hint'])
        self.assertTrue(self.process.terminated)
        self.assertIsNone(self.meeting.reader_task)
        self.assertFalse((self.path / 'config.json').exists())
        self.assertTrue(any(k == 'zoom_join_failed' for k, _ in self.events))
        await self.meeting.leave()  # Idempotent session cleanup.

    async def test_success_progression_and_bridge_readiness_not_short_connecting_error(self):
        self.write(['MEETING_STATUS state=1 error=101 reason=0', 'MEETING_STATUS state=8 error=101 reason=0',
                    'MEETING_STATUS state=10 error=101 reason=0', 'MEETING_STATUS state=1 error=101 reason=0',
                    'MEETING_STATUS state=8 error=101 reason=0', 'MEETING_STATUS state=3 error=101 reason=0'])
        async def receive():
            self.meeting.audio_ready.set()
            self.meeting.mic_ready.set()
            await asyncio.Future()
        self.meeting.receive = receive
        self.meeting.join_timeout = .2
        await self.meeting.join()
        self.assertFalse(self.process.terminated)
        states = [v['meeting_state'] for k, v in self.events if k == 'zoom_join_progress']
        self.assertEqual(states, [1, 8, 10, 1, 8, 3])
        self.assertEqual(self.events[-1][0], 'zoom_audio_ready')

    async def test_admission_and_audio_timeouts_are_distinct(self):
        for state, reason in [(2, 'waiting_for_host_timeout'), (10, 'waiting_room_timeout'),
                              (3, 'audio_readiness_timeout')]:
            with self.subTest(state=state):
                self.meeting.failure = None
                self.process = FakeProcess()
                self.meeting.join_progress = NativeJoinProgress(self.log)
                self.write([f'MEETING_STATUS state={state} error=101 reason=0'])
                with self.assertRaises(ZoomJoinError) as caught:
                    await self.meeting.join()
                self.assertEqual(failure_details(caught.exception)['reason'], reason)

    async def test_native_failure_does_not_wait_for_deadline(self):
        self.write(['MEETING_STATUS state=6 error=8 reason=0'])
        with self.assertRaises(ZoomJoinError) as caught:
            await self.meeting.join()
        self.assertEqual(failure_details(caught.exception)['reason'], 'meeting_failed')
        self.assertEqual(failure_details(caught.exception)['meeting_error'], 8)

    async def test_audio_connect_stall_reports_native_stage_without_stale_success(self):
        self.write(['SDK_INIT result=0', 'AUTO_JOIN_VOIP result=0 enabled=0',
                    'JOIN_REQUEST result=0', 'MEETING_STATUS state=3 error=101 reason=0',
                    'AUDIO_SOURCE_SET result=0', 'JOIN_VOIP_BEGIN'])
        with self.assertRaises(ZoomJoinError) as caught:
            await self.meeting.join()
        fields = failure_details(caught.exception)
        self.assertEqual(fields['reason'], 'audio_readiness_timeout')
        self.assertEqual(fields['native_stage'], 'JOIN_VOIP_BEGIN')
        self.assertNotIn('sdk_result', fields)
        self.assertIn('CoreAudio', fields['hint'])

    async def test_keychain_wait_and_audio_setup_failure_have_distinct_evidence(self):
        progress = NativeJoinProgress(self.log)
        self.assertTrue(progress.feed_line(b'SDK_INIT_BEGIN (check macOS Keychain prompts if this stalls)'))
        self.assertIn('Keychain', progress.snapshot()['hint'])
        for line, reason in [(b'AUTO_JOIN_VOIP result=8 enabled=0', 'audio_join_config_failed'),
                             (b'AUDIO_SOURCE_SET result=8', 'audio_source_failed'),
                             (b'JOIN_VOIP result=8', 'audio_join_failed')]:
            with self.subTest(line=line):
                self.meeting.join_progress = NativeJoinProgress(self.log)
                self.write([line.decode()])
                with self.assertRaises(ZoomJoinError) as caught:
                    self.meeting.check_join_progress()
                self.assertEqual(caught.exception.reason, reason)
        self.assertFalse(progress.feed_line(b'JOIN_VOIP_BEGIN private details'))

    async def test_handshake_hang_is_monitored_and_cancelled(self):
        self.write(['MEETING_STATUS state=1 error=101 reason=0'])
        entered = asyncio.Event()
        async def connect():
            entered.set()
            await asyncio.Future()
        self.meeting.connect = connect
        with self.assertRaises(ZoomJoinError):
            await self.meeting.join()
        self.assertTrue(entered.is_set())
        self.assertTrue(self.process.terminated)

    async def test_user_cancellation_cleans_child_without_timeout_failure(self):
        started = asyncio.Event()
        async def connect():
            started.set()
            await asyncio.Future()
        self.meeting.connect = connect
        self.meeting.join_timeout = 100
        task = asyncio.create_task(self.meeting.join())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(self.process.terminated)
        self.assertFalse(any(k == 'zoom_join_failed' for k, _ in self.events))

    async def test_parser_redacts_and_preserves_partial_lines_bounded(self):
        clock = [10.0]
        progress = NativeJoinProgress(self.log, clock=lambda: clock[0])
        self.log.write_bytes(b'secret token body' + bytes([10]) + b'MEETING_STATUS state=1 err')
        self.assertEqual(progress.read(), [])
        with self.log.open('ab') as stream: stream.write(b'or=101 reason=0' + bytes([10]))
        self.assertEqual(progress.read()[0]['meeting_state'], 1)
        clock[0] = 15
        with self.log.open('ab') as stream:
            stream.write(b'MEETING_STATUS state=1 error=101 reason=0' + bytes([10]))
            stream.write(b'x' * 70000 + bytes([10]))
        progress.read(); progress.read()
        self.assertLessEqual(len(progress.partial), 512)
        self.assertEqual(progress.snapshot()['state_observed_ms'], 5000)
        self.assertNotIn('secret', json.dumps(progress.snapshot()))
        self.assertFalse(progress.feed_line(b'MEETING_STATUS state=1 error=101 reason=0 private'))

    async def test_launch_itself_is_inside_absolute_deadline(self):
        async def launch(): await asyncio.Future()
        self.meeting.launch = launch
        with self.assertRaises(ZoomJoinError) as caught:
            await self.meeting.join()
        self.assertEqual(caught.exception.reason, 'join_timeout')

    async def test_auth_failure_and_receiver_exit_are_structured(self):
        self.write(['SDK_AUTH_RESULT result=8'])
        with self.assertRaises(ZoomJoinError) as caught:
            self.meeting.check_join_progress()
        self.assertEqual(failure_details(caught.exception)['reason'], 'sdk_auth_failed')
        self.assertEqual(failure_details(caught.exception)['sdk_result'], 8)
        self.write(['MEETING_STATUS state=1 error=101 reason=0'])
        self.meeting.join_progress = NativeJoinProgress(self.log)
        self.meeting.process = FakeProcess(returncode=1)
        self.assertEqual(self.meeting.launch_failure().reason, 'receiver_exited_during_join')

    async def test_stuck_shutdown_uses_owned_child_kill_fallback(self):
        class Stuck(FakeProcess):
            def terminate(self): self.terminated = True
            async def wait(self):
                if self.returncode is None:
                    raise TimeoutError()
                return self.returncode
            def kill(self): self.returncode = -9
        process = Stuck()
        self.meeting.process = process
        await self.meeting.leave()
        self.assertTrue(process.terminated)
        self.assertEqual(process.returncode, -9)
        self.assertTrue(any(k == 'zoom_receiver_forced_stop' for k, _ in self.events))
