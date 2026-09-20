import asyncio
import json
import tempfile
import threading
from types import SimpleNamespace
import unittest

from sparkie.audio import AudioFrame
from sparkie.realtime import RealtimeAgent, session_config
from sparkie.realtime_audio import RealtimeLocalAudio, AudioOutput
from sparkie.task_center import TranscriptLedger, TaskCenter


class TaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_clarification_replaces_queued_task_without_duplicate_or_running_mutation(self):
        release = asyncio.Event()
        seen = []
        class Worker:
            async def run(self, request, snapshot):
                seen.append(request)
                await release.wait()
                return 'done'
        with tempfile.TemporaryDirectory() as directory:
            center = TaskCenter(TranscriptLedger(directory), Worker(), lambda *a, **k: None)
            first = center.submit('create file')['task_id']
            second = center.submit('open website')['task_id']
            await asyncio.sleep(0)
            result = center.update(second, 'open https://bowenyu.com')
            self.assertEqual(result['task_id'], second)
            self.assertEqual(len(center.jobs), 2)
            self.assertEqual(center.update(first, 'different file')['error'], 'task_already_started')
            release.set()
            await asyncio.gather(*center.runners.values())
            self.assertEqual(seen, ['create file', 'open https://bowenyu.com'])
            await center.close()

    async def test_queue_is_immediate_and_snapshot_does_not_clip_or_follow_future_speech(self):
        release = asyncio.Event()
        seen = []
        class Worker:
            async def run(self, request, snapshot):
                seen.append(snapshot)
                await release.wait()
                return 'Verified result'
        with tempfile.TemporaryDirectory() as directory:
            ledger = TranscriptLedger(directory)
            for i in range(75):
                ledger.append({'event_id': str(i), 'text': 'long transcript ' * 30})
            events = []
            center = TaskCenter(ledger, Worker(), lambda kind, **fields: events.append(fields))
            result = center.submit('Compare alternatives')
            self.assertEqual(result['status'], 'queued')
            ledger.append({'event_id': 'new', 'text': 'later speech'})
            await asyncio.sleep(0)
            self.assertEqual(len(seen[0]), 75)
            self.assertNotIn('snapshot', events[-1])
            self.assertEqual(center.status(result['task_id'])['status'], 'running')
            release.set()
            await center.runners[result['task_id']]
            self.assertEqual(center.status(result['task_id'])['result'], 'Verified result')
            notice = center.notifications.get_nowait()
            self.assertEqual(notice['result'], 'Verified result')
            self.assertNotIn('snapshot', notice)
            center._save(center.jobs[result['task_id']])
            self.assertTrue(center.notifications.empty())
            from pathlib import Path
            persisted = json.loads((Path(directory) / 'tasks.json').read_text())
            self.assertEqual(len(persisted[0]['snapshot']), 75)
            await center.close()

    async def test_cancellation_before_worker_starts(self):
        class Worker:
            async def run(self, *args): await asyncio.Event().wait()
        with tempfile.TemporaryDirectory() as directory:
            center = TaskCenter(TranscriptLedger(directory), Worker(), lambda *a, **k: None)
            ids = [center.submit(str(i))['task_id'] for i in range(3)]
            fourth = center.submit('fourth task')
            self.assertEqual(fourth['status'], 'queued')
            ids.append(fourth['task_id'])
            await center.close()
            self.assertTrue(all(center.status(i)['status'] == 'cancelled' for i in ids))


class RealtimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_diagnostics_omit_provider_bodies_and_unknown_codes(self):
        from sparkie.providers import ProviderError, failure_details
        for code, expected in [('server_error', 'server_error'),
                               ('sk-private-secret', 'unknown_provider_error')]:
            with self.assertRaises(ProviderError) as caught:
                await self.agent.handle({'type': 'response.done', 'response': {
                    'id': 'r', 'status': 'failed', 'status_details': {
                        'error': {'code': code, 'message': 'private response body'}}}})
            details = failure_details(caught.exception)
            self.assertEqual(details['provider'], 'openai')
            self.assertEqual(details['reason'], 'realtime_response_failed')
            self.assertEqual(details['provider_code'], expected)
            self.assertNotIn('private', json.dumps(details))
        self.assertNotIn('secret', json.dumps(failure_details(RuntimeError('secret'))))

    async def asyncSetUp(self):
        self.events = []
        self.audio = RealtimeLocalAudio(echo_mode='headphones')
        self.audio._loop = asyncio.get_running_loop()
        self.sent = []
        class WS:
            async def send(inner, event): self.sent.append(json.loads(event))
        class Tasks:
            count = 0
            def submit(inner, request): inner.count += 1; return {'task_id': 'id', 'status': 'queued'}
        self.tasks = Tasks()
        self.agent = RealtimeAgent('secret', self.audio, self.tasks, lambda kind, **kw: self.events.append(kind))
        self.agent.ws = WS()

    async def test_tool_returns_without_waiting_for_worker_and_continues_once(self):
        await self.agent.handle({'type': 'response.created', 'response': {'id': 'r'}})
        event = {'type': 'response.function_call_arguments.done', 'response_id': 'r', 'call_id': 'c',
                 'name': 'delegate_task', 'arguments': '{"request":"analyze"}'}
        await self.agent.handle(event)
        await self.agent.handle(event)
        self.assertEqual(self.tasks.count, 1)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['item']['type'], 'function_call_output')
        await self.agent.handle({'type': 'response.done', 'response': {'id': 'r', 'status': 'completed'}})
        self.assertEqual(self.sent[-1]['type'], 'response.create')

    async def test_interrupt_truncates_played_audio_and_ignores_late_chunks(self):
        import base64
        await self.agent.handle({'type': 'response.created', 'response': {'id': 'r'}})
        delta = {'type': 'response.output_audio.delta', 'response_id': 'r', 'item_id': 'i',
                 'delta': base64.b64encode(b'\1\0' * 2400).decode()}
        await self.agent.handle(delta)
        await self.agent.interrupt()
        self.assertEqual(self.sent[-1]['type'], 'conversation.item.truncate')
        self.assertEqual(self.sent[-1]['audio_end_ms'], 0)
        await self.agent.handle(delta)
        self.assertEqual(self.audio.output.generated, 4800)
        self.assertTrue(self.audio.output.cancelled.is_set())
        self.assertTrue(self.audio.output.chunks.empty())
        self.assertFalse(self.audio.output.pending)
        self.assertFalse(self.audio.waiting_outputs)

    async def test_stream_callback_joins_chunks_without_padding_between_deltas(self):
        self.audio.append_output('i', b'\1\0' * 2)
        self.audio.append_output('i', b'\2\0' * 3)
        self.audio.finish_output('i')
        output = bytearray(12)
        timing = SimpleNamespace(inputBufferAdcTime=0, outputBufferDacTime=0, currentTime=0)
        status = SimpleNamespace(input_overflow=False, output_underflow=False)
        self.audio._callback(bytes(12), output, 6, timing, status)
        self.assertEqual(output, b'\1\0' * 2 + b'\2\0' * 3 + b'\0\0')
        self.assertEqual(self.audio.output.scheduled, 10)
        self.assertEqual(self.audio.gated_samples, 0)

    async def test_played_time_excludes_underrun_and_future_dac_blocks(self):
        output = AudioOutput('i')
        output.blocks = [(10, 4800), (11, 4800)]
        self.assertEqual(output.played_ms(10.5), 100)
        self.assertEqual(output.played_ms(11.05), 150)

    async def test_server_vad_and_native_audio_are_configured(self):
        config = session_config('gpt-realtime-2.1')['session']
        self.assertEqual(config['audio']['input']['format']['rate'], 24000)
        self.assertTrue(config['audio']['input']['turn_detection']['interrupt_response'])

    async def test_next_output_does_not_overwrite_unplayed_previous_audio(self):
        self.audio.append_output('first', b'\1\0' * 2)
        self.audio.finish_output('first')
        self.audio.append_output('second', b'\2\0' * 2)
        self.audio.finish_output('second')
        timing = SimpleNamespace(inputBufferAdcTime=0, outputBufferDacTime=0, currentTime=0)
        status = SimpleNamespace(input_overflow=False, output_underflow=False)
        output = bytearray(4)
        self.audio._callback(bytes(4), output, 2, timing, status)
        self.assertEqual(output, b'\1\0' * 2)
        self.audio._callback(bytes(4), output, 2, timing, status)
        self.assertEqual(output, b'\2\0' * 2)

    async def test_speaker_gate_blocks_echo_during_stream_gaps_and_tail_then_resumes(self):
        from unittest.mock import patch
        self.audio.echo_mode = 'speaker'
        timing = SimpleNamespace(inputBufferAdcTime=0, outputBufferDacTime=0, currentTime=0)
        status = SimpleNamespace(input_overflow=False, output_underflow=False)
        echo = b'\x40\x1f' * 240  # Speaker sound picked up by the microphone.
        self.audio.append_output('reply', echo)
        output = bytearray(len(echo))
        with patch('sparkie.realtime_audio.time.monotonic', return_value=100):
            self.audio._callback(echo, output, 240, timing, status)
        self.assertEqual(bytes(output), echo)
        self.assertEqual(self.audio._queue.get_nowait().pcm, bytes(len(echo)))
        # No next packet yet, but generation is still active: gate must stay closed.
        with patch('sparkie.realtime_audio.time.monotonic', return_value=100.2):
            self.audio._callback(echo, output, 240, timing, status)
        self.assertEqual(self.audio._queue.get_nowait().pcm, bytes(len(echo)))
        self.audio.finish_output('reply')
        # Room/speaker tail after final output is protected too.
        with patch('sparkie.realtime_audio.time.monotonic', return_value=100.4):
            self.audio._callback(echo, output, 240, timing, status)
        self.assertEqual(self.audio._queue.get_nowait().pcm, bytes(len(echo)))
        with patch('sparkie.realtime_audio.time.monotonic', return_value=100.7):
            self.audio._callback(echo, output, 240, timing, status)
        self.assertEqual(self.audio._queue.get_nowait().pcm, echo)
        self.assertEqual(self.audio.gated_samples, 720)

    async def test_headphones_intentionally_keep_microphone_open_for_barge_in(self):
        timing = SimpleNamespace(inputBufferAdcTime=0, outputBufferDacTime=0, currentTime=0)
        status = SimpleNamespace(input_overflow=False, output_underflow=False)
        speech = b'\x40\x1f' * 240
        self.audio.append_output('reply', speech)
        self.audio._callback(speech, bytearray(len(speech)), 240, timing, status)
        self.assertEqual(self.audio._queue.get_nowait().pcm, speech)
        self.assertEqual(self.audio.gated_samples, 0)

    async def test_pending_continuation_prevents_duplicate_response_and_overlap_is_recoverable(self):
        await self.agent.request_response()
        await self.agent.request_response()
        self.assertEqual(sum(e['type']=='response.create' for e in self.sent),1)
        await self.agent.handle({'type':'error','error':{'code':'conversation_already_has_active_response'}})
        self.assertIn('response_overlap',self.events)
        await self.agent.handle({'type':'input_audio_buffer.speech_started'})
        await self.agent.request_response()
        self.assertEqual(sum(e['type']=='response.create' for e in self.sent),1)

    async def test_completion_wakes_idle_frontend_once_after_speech_and_playback(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tasks = TaskCenter(TranscriptLedger(directory.name), None, lambda *a, **k: None)
        self.agent.tasks = self.tasks
        self.agent.ready.set()
        self.agent.user_speaking = True
        self.audio.append_output('playing', b'\1\0' * 480)
        self.tasks.jobs['done'] = {'task_id': 'done', 'status': 'completed', 'result': '42'}
        self.tasks._save(self.tasks.jobs['done'])
        notifier = asyncio.create_task(self.agent.notify_tasks())
        try:
            await asyncio.sleep(.12)
            self.assertEqual(self.sent, [])
            self.agent.user_speaking = False
            await asyncio.sleep(.12)
            self.assertEqual(self.sent, [])
            await self.audio.stop_speaking()
            await asyncio.sleep(.12)
            self.assertEqual([e['type'] for e in self.sent], ['conversation.item.create', 'response.create'])
            self.assertIn('42', self.sent[0]['item']['content'][0]['text'])
            await asyncio.sleep(.12)
            self.assertEqual(len(self.sent), 2)
        finally:
            notifier.cancel()
            await asyncio.gather(notifier, return_exceptions=True)

    async def test_remain_silent_does_not_trigger_spoken_continuation(self):
        await self.agent.handle({'type': 'response.created', 'response': {'id': 'silent'}})
        await self.agent.handle({'type': 'response.function_call_arguments.done', 'response_id': 'silent',
                                 'call_id': 'choice', 'name': 'remain_silent', 'arguments': '{}'})
        await self.agent.handle({'type': 'response.done', 'response': {'id': 'silent', 'status': 'completed'}})
        self.assertEqual([e['type'] for e in self.sent], ['conversation.item.create'])
        self.assertIn('realtime_silent', self.events)
