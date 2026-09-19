"""Offline Zoom transport tests; fake SDK progress is not real meeting evidence."""
import asyncio
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import numpy as np
from sparkie.audio import AudioFrame
from sparkie.providers import ProviderError
from sparkie.realtime_zoom_audio import PCMResampler, RealtimeZoomAudio
from sparkie.realtime import RealtimeAgent


class ResamplerTests(unittest.TestCase):
    def test_stream_boundaries_do_not_change_signal_or_duration(self):
        for source, target in [(32000, 24000), (24000, 32000)]:
            signal = (12000 * np.sin(np.arange(source) * (2 * np.pi * 1000 / source))).astype('<i2').tobytes()
            whole = PCMResampler(source, target).feed(signal, final=True)
            stream = PCMResampler(source, target)
            chunks = [stream.feed(signal[i:i+638]) for i in range(0, len(signal), 638)]
            chunks.append(stream.feed(b'', final=True))
            actual = b''.join(chunks)
            self.assertEqual(len(actual), target * 2)
            # Integer dithering may differ by a few LSB; boundaries must not add clicks.
            a, b = np.frombuffer(actual, '<i2').astype(float), np.frombuffer(whole, '<i2').astype(float)
            self.assertLess(np.max(np.abs(a - b)), 5)
            self.assertGreater(np.sqrt(np.mean(a*a)), 8000)


class Meeting:
    def __init__(self):
        self.packets = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False
        self.stopped = False
        self.fail = False
        self.stop_calls = 0
    async def join(self): pass
    async def play_audio(self, pcm, rate):
        self.packets.append((pcm, rate))
        self.started.set()
        if self.fail:
            raise RuntimeError('SDK disconnected')
        if self.block:
            await self.release.wait()
        await asyncio.sleep(.001)
    async def stop_speaking(self): self.stop_calls += 1
    async def leave(self): self.stopped = True
    def request_stop(self): self.stopped = True
    async def audio(self):
        for i in range(100):
            if self.stopped:
                return
            await asyncio.sleep(0)
            yield AudioFrame(i, bytes(640), 32000)
    def diagnostics(self): return {'remote_audible_latency_measured': False}


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.meeting = Meeting()
        self.events = []
        self.audio = RealtimeZoomAudio(self.meeting, on_event=lambda kind, **kw: self.events.append((kind, kw)))
        await self.audio.join()
    async def asyncTearDown(self): await self.audio.leave()

    async def wait_drained(self, ident):
        async with asyncio.timeout(2):
            while not self.audio.outputs[ident].drained:
                await asyncio.sleep(.001)

    async def test_input_is_real_resampled_pcm24k(self):
        frames = [frame async for frame in self.audio.audio()]
        self.assertTrue(all(frame.sample_rate == 24000 for frame in frames))
        self.assertEqual(sum(len(frame.pcm) for frame in frames), 48000)
        self.assertEqual(self.audio.captured_samples, 24000)

    async def test_streams_before_generation_done_and_flushes_final_samples(self):
        self.audio.append_output('answer', bytes(24000))  # half second
        await asyncio.wait_for(self.meeting.started.wait(), 1)
        self.assertFalse(self.audio.outputs['answer'].finished)
        self.audio.append_output('answer', bytes(4810))
        self.audio.finish_output('answer')
        await self.wait_drained('answer')
        # Rounded rational conversion length; no per-chunk rate reset or lost tail.
        self.assertEqual(sum(len(pcm) for pcm, _ in self.meeting.packets), round(28810 / 2 * 4 / 3) * 2)
        self.assertTrue(all(rate == 32000 and len(pcm) <= 6400 for pcm, rate in self.meeting.packets))
        self.assertEqual(self.audio.outputs['answer'].played_ms(), 28810 // 48)
        self.assertFalse(self.audio.diagnostics()['remote_audibility_verified'])
        self.assertFalse(any(kind == 'realtime_audio_started' for kind, _ in self.events))

    async def test_interrupt_clears_pending_audio_and_new_response_can_play(self):
        self.meeting.block = True
        self.audio.append_output('old', bytes(48000))
        self.audio.finish_output('old')
        await asyncio.wait_for(self.meeting.started.wait(), 1)
        await self.audio.stop_speaking()
        self.assertEqual(self.audio.buffered, 0)
        self.assertEqual(self.audio.outputs['old'].played_ms(), 0)  # in-flight packet unconfirmed
        self.audio.append_output('old', bytes(960))  # late delta cannot revive it
        self.assertEqual(self.audio.buffered, 0)
        self.meeting.block = False
        self.audio.append_output('new', bytes(4800))
        self.audio.finish_output('new')
        await self.wait_drained('new')
        self.assertEqual(self.audio.outputs['new'].played_ms(), 100)
        self.assertEqual(len(self.meeting.packets), 2)

    async def test_queue_overflow_is_explicit(self):
        with self.assertRaises(ProviderError):
            self.audio.append_output('too-large', bytes(48000 * 16))

    async def test_generation_burst_cancels_reply_without_killing_session(self):
        import base64
        self.meeting.block = True
        events = []
        agent = RealtimeAgent('fake', self.audio, None,
                              lambda kind, **kw: events.append((kind, kw)))
        agent.ws = SimpleNamespace(send=AsyncMock())
        await agent.handle({'type': 'response.created', 'response': {'id': 'burst'}})
        # Faster-than-playback generation exceeds the bounded 15-second queue.
        await agent.handle({'type': 'response.output_audio.delta', 'response_id': 'burst',
                            'item_id': 'long', 'delta': base64.b64encode(bytes(48000 * 16)).decode()})
        self.assertEqual(self.audio.buffered, 0)
        self.assertTrue(self.audio.outputs['long'].cancelled.is_set())
        messages = [json.loads(c.args[0]) for c in agent.ws.send.await_args_list]
        self.assertEqual(messages[-2]['type'], 'response.cancel')
        self.assertEqual(messages[-1]['type'], 'conversation.item.truncate')
        self.assertEqual(messages[-1]['audio_end_ms'], 0)
        self.assertTrue(any(kind == 'realtime_playback_limited' for kind, _ in events))
        await agent.handle({'type': 'response.output_audio.delta', 'response_id': 'burst',
                            'item_id': 'long', 'delta': base64.b64encode(bytes(4800)).decode()})
        self.assertEqual(self.audio.buffered, 0)
        await agent.handle({'type': 'response.done', 'response': {'id': 'burst', 'status': 'cancelled'}})
        self.meeting.block = False
        await agent.handle({'type': 'response.created', 'response': {'id': 'next'}})
        await agent.handle({'type': 'response.output_audio.delta', 'response_id': 'next',
                            'item_id': 'next', 'delta': base64.b64encode(bytes(4800)).decode()})
        await agent.handle({'type': 'response.output_audio.done', 'item_id': 'next'})
        await self.wait_drained('next')
        self.assertEqual(self.audio.outputs['next'].played_ms(), 100)

    async def test_sdk_failure_stops_input_and_propagates(self):
        self.meeting.fail = True
        self.audio.append_output('failed', bytes(4800))
        self.audio.finish_output('failed')
        async with asyncio.timeout(1):
            while self.audio.failure is None:
                await asyncio.sleep(.001)
        with self.assertRaisesRegex(RuntimeError, 'SDK disconnected'):
            _ = [frame async for frame in self.audio.audio()]

    async def test_agent_uses_conservative_progress_for_truncation(self):
        self.meeting.block = True
        self.audio.append_output('item', bytes(48000))
        await asyncio.wait_for(self.meeting.started.wait(), 1)
        agent = RealtimeAgent('fake', self.audio, None, lambda *a, **k: None)
        agent.ws = SimpleNamespace(send=AsyncMock())
        agent.response_id = 'response'
        await agent.interrupt()
        messages = [json.loads(call.args[0]) for call in agent.ws.send.await_args_list]
        self.assertEqual(messages[-1]['type'], 'conversation.item.truncate')
        self.assertEqual(messages[-1]['audio_end_ms'], 0)

    async def test_background_notification_waits_for_zoom_output(self):
        self.meeting.block = True
        self.audio.append_output('item', bytes(4800))
        self.audio.finish_output('item')
        agent = RealtimeAgent('fake', self.audio, None, lambda *a, **k: None)
        self.assertFalse(agent.notification_ready())
        self.meeting.release.set()
        await self.wait_drained('item')
        self.assertTrue(agent.notification_ready())

    async def test_delegated_task_does_not_block_zoom_input_and_result_reaches_frontend(self):
        from sparkie.task_center import TranscriptLedger, TaskCenter
        release = asyncio.Event()
        class Worker:
            async def run(self, request, transcript):
                await release.wait()
                return 'Verified synthetic research result'
        with tempfile.TemporaryDirectory() as directory:
            center = TaskCenter(TranscriptLedger(Path(directory)), Worker(), lambda *a, **k: None)
            agent = RealtimeAgent('fake', self.audio, center, lambda *a, **k: None)
            agent.ws = SimpleNamespace(send=AsyncMock())
            agent.ready.set()
            notifier = asyncio.create_task(agent.notify_tasks())
            try:
                await agent.handle({'type': 'response.function_call_arguments.done', 'response_id': 'r',
                                    'call_id': 'c', 'name': 'delegate_task',
                                    'arguments': json.dumps({'request': 'Research a synthetic topic'})})
                job = next(iter(center.jobs.values()))
                self.assertIn(job['status'], ('queued', 'running'))
                # Conference input can continue into the real frontend while its task is pending.
                async for frame in self.audio.audio():
                    await agent.append(frame)
                self.assertGreater(agent.sent_seconds, .9)
                self.assertNotEqual(job['status'], 'completed')
                release.set()
                async with asyncio.timeout(2):
                    while not any(json.loads(c.args[0]).get('type') == 'response.create'
                                  for c in agent.ws.send.await_args_list):
                        await asyncio.sleep(.01)
                messages = [json.loads(c.args[0]) for c in agent.ws.send.await_args_list]
                self.assertTrue(any('Verified synthetic research result' in json.dumps(m) for m in messages))
                self.assertEqual(job['status'], 'completed')
            finally:
                notifier.cancel()
                await asyncio.gather(notifier, return_exceptions=True)
                await center.close()


class CLISelectionTests(unittest.TestCase):
    def test_zoom_defaults_to_realtime_not_legacy_tts(self):
        from sparkie.primitive import main
        with patch('sparkie.primitive.load_dotenv'), \
             patch('sys.argv', ['sparkie', 'zoom']), \
             patch('sparkie.realtime_session.run', new=AsyncMock(return_value=0)) as run:
            with self.assertRaises(SystemExit) as result:
                main()
            self.assertEqual(result.exception.code, 0)
            args = run.await_args.args[0]
            self.assertEqual(args.transport, 'zoom')
            self.assertEqual(args.response_mode, 'realtime')


class SessionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_zoom_pcm_goes_to_both_providers_and_uses_task_center(self):
        from sparkie import realtime_session
        from sparkie.task_center import TaskCenter
        from sparkie.contracts import TranscriptEvent
        received, captured_centers = [], []
        meeting = Meeting()
        class Agent:
            def __init__(self, key, audio, center, emit, **kwargs):
                self.ready = asyncio.Event()
                self.model = 'test'
                self.last_speech_end = None
                captured_centers.append(center)
            async def run(self): self.ready.set(); await asyncio.Event().wait()
            async def append(self, frame): received.append(frame)
            async def notify_tasks(self): await asyncio.Event().wait()
        class Ears:
            def __init__(self, *args, **kw):
                self.model, self.language, self.rate = kw['model'], kw['language'], kw['rate']
                self.on_ready = kw['on_ready']
            async def transcribe(self, frames):
                self.on_ready()
                async for frame in frames:
                    self.assert_rate = frame.sample_rate
                yield TranscriptEvent('test', 'e1', 0, 'Please research this question.')
        with tempfile.TemporaryDirectory() as directory:
            read_fd, write_fd = os.pipe()
            os.close(write_fd)
            with os.fdopen(read_fd) as stdin, \
                 patch.dict(os.environ, {'OPENAI_API_KEY': 'fake', 'DEEPGRAM_API_KEY': 'fake', 'ZOOM_PLATFORM': 'macos'}), \
                 patch('sparkie.zoom_audio.ZoomMacAudioMeeting', return_value=meeting), \
                 patch.object(realtime_session, 'RealtimeAgent', Agent), \
                 patch.object(realtime_session, 'DeepgramEars', Ears), \
                 patch('sys.stdin', stdin), redirect_stdout(io.StringIO()):
                args = SimpleNamespace(transport='zoom', seconds=10, language='en', output=Path(directory))
                old_umask = os.umask(0o077)
                try:
                    self.assertEqual(await realtime_session.run(args), 0)
                finally:
                    os.umask(old_umask)
            self.assertEqual(sum(len(f.pcm) for f in received), 48000)
            self.assertTrue(all(f.sample_rate == 24000 for f in received))
            self.assertIsInstance(captured_centers[0], TaskCenter)
            path = next(Path(directory).iterdir())
            self.assertIn('Please research', (path / 'transcript.jsonl').read_text())
            report = json.loads((path / 'run.json').read_text())
            self.assertEqual(report['transport'], 'zoom')
            self.assertEqual(report['audio']['transport'], 'zoom-realtime')
            self.assertFalse(report['remote_audibility_verified'])
            self.assertTrue(meeting.stopped)
