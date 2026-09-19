"""Fast offline controls and PCM tests; no native SDK or provider initialization."""
import asyncio
import base64
import json
from pathlib import Path
import tempfile
import unittest

from sparkie.audio import AudioFrame
from sparkie.realtime import RealtimeAgent, session_config
from sparkie.realtime_zoom_audio import RealtimeZoomAudio
from sparkie.task_center import TaskCenter, TranscriptLedger


class Bridge:
    def __init__(self):
        self.packets = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = 0
    async def join(self): pass
    async def leave(self): pass
    def request_stop(self): pass
    async def play_audio(self, pcm, rate):
        self.packets.append(pcm)
        self.entered.set()
        await self.release.wait()
    async def stop_speaking(self):
        self.cancelled += 1  # Fake existing cancel-v1 barrier; no SDK invocation.


class InterruptionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.events, self.sent = [], []
        emit = lambda kind, **fields: self.events.append((kind, fields))
        self.center = TaskCenter(TranscriptLedger(self.directory.name), None, emit)
        self.bridge = Bridge()
        self.audio = RealtimeZoomAudio(self.bridge, on_event=emit)
        await self.audio.join()
        self.agent = RealtimeAgent('unused', self.audio, self.center, emit)
        sent = self.sent
        class WS:
            async def send(self, message): sent.append(json.loads(message))
        self.agent.ws = WS()
        self.addAsyncCleanup(self.audio.leave)

    def complete(self, task_id):
        job = {'task_id': task_id, 'status': 'completed', 'result': 'Result ' + task_id}
        self.center.jobs[task_id] = job
        self.center._save(job)

    async def created(self, response):
        await self.agent.handle({'type': 'response.created', 'response': {'id': response}})

    async def done(self, response):
        await self.agent.handle({'type': 'response.done', 'response': {'id': response, 'status': 'completed'}})

    async def audio_item(self, response, item):
        await self.agent.handle({'type': 'response.output_audio.delta', 'response_id': response,
                                 'item_id': item, 'delta': base64.b64encode(bytes([1, 0]) * 4800).decode()})
        await self.agent.handle({'type': 'response.output_audio_transcript.done', 'response_id': response,
                                 'item_id': item, 'transcript': 'Draft ' + item})
        await self.agent.handle({'type': 'response.output_audio.done', 'response_id': response, 'item_id': item})

    async def human(self, turn, phase, **kwargs):
        await self.agent.control({'action': 'human_turn', 'turn_id': turn, 'source': 'human', 'phase': phase, **kwargs})

    def pending(self):
        return [j['task_id'] for j in self.center.pending_announcements()]

    async def test_all_pcm_discarded_and_semantics_regenerated_after_user_turn(self):
        await self.created('reply')
        await self.audio_item('reply', 'playing')
        await self.done('reply')
        await asyncio.wait_for(self.bridge.entered.wait(), .5)
        self.complete('task-a')
        await self.agent.request_response()
        await self.created('announcement')
        await self.audio_item('announcement', 'task-audio')
        await self.audio_item('announcement', 'later-answer')
        await self.done('announcement')
        creates = sum(m['type'] == 'response.create' for m in self.sent)
        await self.human('turn-1', 'start')
        self.assertEqual(self.bridge.cancelled, 1)
        self.assertEqual(self.audio.buffered, 0)
        self.assertFalse(self.audio.waiting)
        self.assertTrue(all(o.cancelled.is_set() and not o.pending and o.resampler is None
                            for o in self.audio.outputs.values()))
        truncations = [m for m in self.sent if m['type'] == 'conversation.item.truncate']
        self.assertEqual([m['item_id'] for m in truncations], ['playing', 'task-audio', 'later-answer'])
        self.assertTrue(all(m['audio_end_ms'] == 0 for m in truncations))
        self.assertEqual(self.pending(), ['task-a'])
        await self.human('turn-1', 'start')
        await self.agent.interrupt()
        await self.audio_item('announcement', 'late-unseen')
        self.assertNotIn('late-unseen', self.audio.outputs)
        self.bridge.release.set()
        await asyncio.sleep(0)
        self.assertEqual(len(self.bridge.packets), 1)
        self.assertEqual(sum(m['type'] == 'response.create' for m in self.sent), creates)
        await self.human('turn-1', 'commit', text='Stop; just tell me the conclusion.')
        self.assertEqual(sum(m['type'] == 'response.create' for m in self.sent), creates + 1)
        context = self.sent[-2]['item']['content'][0]['text']
        self.assertIn('Result task-a', context)
        self.assertIn('Draft later-answer', context)
        self.assertIn('NOT statements the user heard', context)
        await self.created('fresh')
        await self.audio_item('fresh', 'fresh-waveform')
        async with asyncio.timeout(.5):
            while not self.audio.outputs['fresh-waveform'].drained:
                await asyncio.sleep(0)
        self.assertEqual(len(self.bridge.packets), 3)

    async def test_confirmation_and_repeated_interrupts_preserve_order(self):
        for task in ('first', 'second', 'third'):
            self.complete(task)
        await self.agent.request_response()
        await self.created('initial')
        await self.audio_item('initial', 'queued')
        await self.agent.control({'action': 'confirm_delivery', 'source': 'human', 'task_id': 'first', 'attempt': 1})
        await self.human('one', 'start')
        await self.agent.interrupt()
        self.assertEqual(self.pending(), ['second', 'third'])
        await self.done('initial')
        await self.human('one', 'commit', text='Give me the remaining results.')
        context = self.sent[-2]['item']['content'][0]['text']
        self.assertNotIn('Result first', context)
        self.assertLess(context.index('Result second'), context.index('Result third'))
        await self.created('retry')
        await self.audio_item('retry', 'retry-audio')
        with self.assertRaises(ValueError):
            await self.agent.control({'action': 'confirm_delivery', 'source': 'human', 'task_id': 'second', 'attempt': 1})
        await self.human('two', 'start')
        await self.done('retry')
        self.assertEqual(self.pending(), ['second', 'third'])
        await self.human('two', 'commit', text='Try again briefly.')
        self.assertEqual(self.center.status('second')['announcement']['attempt'], 3)
        persisted = json.loads((Path(self.directory.name) / 'tasks.json').read_text())
        self.assertEqual([j['announcement']['state'] for j in persisted], ['confirmed', 'offered', 'offered'])
        self.assertFalse(any(k == 'background_notification_delivered' for k, _ in self.events))

    async def test_late_response_created_cancelled_before_fresh_generation(self):
        self.complete('result')
        await self.agent.request_response()
        await self.human('t', 'start')
        await self.human('t', 'commit', text='New question')
        self.assertEqual(sum(m['type'] == 'response.create' for m in self.sent), 1)
        await self.created('stale')
        await self.audio_item('stale', 'stale-item')
        self.assertFalse(self.audio.outputs)
        await self.done('stale')
        self.assertEqual(sum(m['type'] == 'response.create' for m in self.sent), 2)
        self.assertEqual(self.center.status('result')['announcement']['attempt'], 2)
        self.assertTrue(any(m['type'] == 'conversation.item.truncate' and m['item_id'] == 'stale-item' for m in self.sent))

    async def test_human_boundary_rejects_bot_and_deduplicates_commit_and_vad(self):
        with self.assertRaises(ValueError):
            await self.agent.control({'action': 'human_turn', 'source': 'bot', 'turn_id': 'x', 'phase': 'start'})
        self.assertFalse(self.agent.awaiting_turn)
        await self.human('x', 'start')
        await self.agent.append(AudioFrame(0, bytes([1, 0]) * 240, 24000))
        self.assertFalse(any(base64.b64decode(self.sent[-1]['audio'])))
        await self.agent.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'mixed'})
        await self.human('x', 'commit', text='Real separated human text')
        await self.agent.handle({'type': 'input_audio_buffer.committed', 'item_id': 'mixed'})
        await self.human('x', 'commit', text='duplicate')
        self.assertEqual(sum(m['type'] == 'response.create' for m in self.sent), 1)
        self.assertEqual(sum(k == 'human_turn_committed' for k, _ in self.events), 1)
        self.assertTrue(any(m['type'] == 'conversation.item.delete' and m['item_id'] == 'mixed' for m in self.sent))

    async def test_vad_commit_not_speech_stop_triggers_response_idle_preserves_pcm(self):
        self.assertFalse(session_config('test')['session']['audio']['input']['turn_detection']['create_response'])
        await self.agent.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'human'})
        self.assertFalse(self.audio.input_gated())
        await self.agent.handle({'type': 'input_audio_buffer.speech_stopped', 'item_id': 'human'})
        self.assertFalse(any(m['type'] == 'response.create' for m in self.sent))
        for _ in range(2):
            await self.agent.handle({'type': 'input_audio_buffer.committed', 'item_id': 'human'})
        self.assertEqual(sum(m['type'] == 'response.create' for m in self.sent), 1)

    async def test_submitted_is_unconfirmed_but_idle_speech_does_not_repeat(self):
        self.complete('result')
        await self.agent.request_response()
        await self.created('r')
        self.bridge.release.set()
        await self.audio_item('r', 'played')
        await self.done('r')
        async with asyncio.timeout(.5):
            while not self.audio.outputs['played'].drained:
                await asyncio.sleep(0)
        self.assertEqual(self.center.status('result')['announcement']['state'], 'offered')
        await self.agent.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'next'})
        self.assertEqual(self.pending(), [])
        await self.agent.handle({'type': 'input_audio_buffer.committed', 'item_id': 'next'})
        self.assertEqual(self.center.status('result')['announcement']['attempt'], 1)

    async def test_notification_wakes_once_and_remains_durable(self):
        self.complete('result')
        self.agent.ready.set()
        notifier = asyncio.create_task(self.agent.notify_tasks())
        try:
            async with asyncio.timeout(.5):
                while not self.sent:
                    await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertEqual([m['type'] for m in self.sent], ['conversation.item.create', 'response.create'])
            self.assertEqual(self.center.status('result')['announcement']['state'], 'offered')
            self.assertTrue(self.center.notifications.empty())
        finally:
            notifier.cancel()
            await asyncio.gather(notifier, return_exceptions=True)

    async def test_unfinished_stream_is_truncated_at_submitted_progress(self):
        await self.created('stream')
        await self.agent.handle({'type': 'response.output_audio.delta', 'response_id': 'stream',
                                 'item_id': 'gap', 'delta': base64.b64encode(bytes(9600)).decode()})
        output = self.audio.outputs['gap']
        # Generation can pause with all known audio submitted but no audio.done yet.
        output.submitted = 12800
        await self.agent.interrupt()
        truncations = [m for m in self.sent if m['type'] == 'conversation.item.truncate']
        self.assertEqual(truncations[-1]['audio_end_ms'], 200)
        await self.agent.interrupt()
        self.assertEqual(len([m for m in self.sent if m['type'] == 'conversation.item.truncate']), 1)

    async def test_cancelled_tool_gets_output_without_executing_task(self):
        await self.created('tool')
        await self.agent.interrupt()
        event = {'type': 'response.function_call_arguments.done', 'response_id': 'tool',
                 'call_id': 'late-tool', 'name': 'delegate_task', 'arguments': '{"request":"do work"}'}
        await self.agent.handle(event)
        await self.agent.handle(event)
        self.assertEqual(self.center.jobs, {})
        results = [m['item'] for m in self.sent if m.get('item', {}).get('call_id') == 'late-tool']
        self.assertEqual(len(results), 1)
        self.assertIn('interrupted_before_execution', results[0]['output'])

    async def test_task_continuation_and_new_completion_survive_interruption(self):
        self.complete('first')
        await self.agent.request_response()
        await self.created('tool')
        await self.agent.handle({'type': 'response.function_call_arguments.done', 'response_id': 'tool',
                                 'call_id': 'status', 'name': 'task_status',
                                 'arguments': '{"task_id":"first"}'})
        await self.done('tool')
        await self.created('continuation')
        await self.audio_item('continuation', 'announcement')
        await self.human('turn', 'start')
        self.complete('second')
        await self.done('continuation')
        self.assertEqual(self.pending(), ['first', 'second'])
        await self.human('turn', 'commit', text='Give me both results briefly.')
        context = self.sent[-2]['item']['content'][0]['text']
        self.assertLess(context.index('Result first'), context.index('Result second'))
        self.assertEqual(self.center.status('first')['announcement']['attempt'], 2)
        self.assertEqual(self.center.status('second')['announcement']['attempt'], 1)

    async def test_cancel_failure_preserves_pending_result_and_prevents_replacement(self):
        self.complete('result')
        await self.agent.request_response()
        await self.created('r')
        await self.audio_item('r', 'playing')
        async def fail_cancel():
            raise RuntimeError('fake disconnected bridge')
        self.bridge.stop_speaking = fail_cancel
        with self.assertRaises(RuntimeError):
            await self.agent.interrupt()
        self.assertEqual(self.pending(), ['result'])
        self.assertTrue(self.agent.awaiting_turn)
        self.assertIsNotNone(self.audio.failure)
        self.assertEqual(self.audio.buffered, 0)

    async def test_public_request_serializes_with_interrupt_without_reentrancy(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.agent.ws.send
        async def blocked(message):
            if json.loads(message)['type'] == 'conversation.item.create':
                entered.set()
                await release.wait()
            await original(message)
        self.agent.ws.send = blocked
        self.complete('task')
        request = asyncio.create_task(self.agent.request_response())
        await asyncio.wait_for(entered.wait(), .5)
        interrupt = asyncio.create_task(self.agent.interrupt())
        await asyncio.sleep(0)
        self.assertFalse(interrupt.done())
        release.set()
        await asyncio.wait_for(asyncio.gather(request, interrupt), .5)
        self.assertEqual(self.pending(), ['task'])
        await self.agent.handle({'type': 'input_audio_buffer.committed', 'item_id': 'human'})
        await self.created('old')
        await self.done('old')
        self.assertEqual(sum(m['type'] == 'response.create' for m in self.sent), 2)
        await self.created('new')
        await self.created('old')
        await self.done('old')
        self.assertEqual(self.agent.response_id, 'new')

    async def test_task_stub_notifications_survive_interruption(self):
        from types import SimpleNamespace
        self.agent.tasks = SimpleNamespace(notifications=asyncio.Queue())
        self.agent.tasks.notifications.put_nowait({'task_id': 'stub', 'status': 'completed', 'result': 'legacy result'})
        self.agent.ready.set()
        notifier = asyncio.create_task(self.agent.notify_tasks())
        try:
            async with asyncio.timeout(.5):
                while not self.agent.response_pending:
                    await asyncio.sleep(0)
            await self.created('stub-response')
            await self.audio_item('stub-response', 'stub-audio')
            await self.human('stub-turn', 'start')
            await self.done('stub-response')
            await self.human('stub-turn', 'commit', text='Say that again briefly')
            self.assertIn('legacy result', self.sent[-2]['item']['content'][0]['text'])
            self.assertFalse(notifier.done())
            with self.assertRaises(ValueError):
                await self.agent.control({'action': 'confirm_delivery', 'source': 'human', 'task_id': 'stub', 'attempt': 1})
        finally:
            notifier.cancel()
            await asyncio.gather(notifier, return_exceptions=True)

    async def test_completion_during_offer_and_stale_deferral_keep_attempt_order(self):
        self.complete('first')
        original = self.agent.ws.send
        async def complete_during_send(message):
            if 'Delivery context:' in message and 'second' not in self.center.jobs:
                self.complete('second')
            await original(message)
        self.agent.ws.send = complete_during_send
        await self.agent.request_response()
        self.assertEqual(self.pending(), ['second'])
        await self.created('r')
        await self.audio_item('r', 'a')
        await self.human('t', 'start')
        self.assertEqual(self.pending(), ['first', 'second'])
        await self.done('r')
        await self.human('t', 'commit', text='Both results please')
        self.center.defer_announcements([{'task_id': 'first', 'attempt': 1}])
        self.assertEqual(self.pending(), [])
        self.assertTrue(self.center.confirm_announcement('first', 2))
        self.center.defer_announcements([{'task_id': 'first', 'attempt': 2}])
        self.assertEqual(self.center.status('first')['announcement']['state'], 'confirmed')
        persisted = json.loads((Path(self.directory.name) / 'tasks.json').read_text())
        self.assertEqual([j['announcement']['order'] for j in persisted], [0, 1])

    async def test_cancelled_transcript_without_pcm_and_late_duplicates(self):
        await self.created('r')
        await self.human('t', 'start')
        transcript = {'type': 'response.output_audio_transcript.done', 'response_id': 'r',
                      'item_id': 'no-pcm', 'content_index': 2, 'transcript': 'Preserve this information'}
        await self.agent.handle(transcript)
        await self.agent.handle({'type': 'response.output_audio.done', 'response_id': 'r',
                                 'item_id': 'no-pcm', 'content_index': 2})
        await self.done('r')
        await self.human('t', 'commit', text='What matters?')
        self.assertIn('Preserve this information', self.sent[-2]['item']['content'][0]['text'])
        await self.agent.handle(transcript)
        await self.agent.handle({**transcript, 'type': 'response.output_audio_transcript.delta', 'delta': 'duplicate'})
        self.assertEqual(self.agent.recovery, {})
        truncations = [m for m in self.sent if m['type'] == 'conversation.item.truncate']
        self.assertEqual(len(truncations), 1)
        self.assertEqual(truncations[0]['content_index'], 2)
        await self.agent.handle({**transcript, 'item_id': 'later', 'transcript': 'Late final information'})
        self.assertEqual(self.agent.recovery['later']['text'], 'Late final information')
        self.assertTrue(any(m['type'] == 'conversation.item.truncate' and m['item_id'] == 'later' for m in self.sent))

    async def test_overlapping_vad_turns_wait_for_latest_commit_and_ignore_duplicates(self):
        await self.created('old')
        await self.agent.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'one'})
        await self.agent.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'two'})
        await self.agent.handle({'type': 'input_audio_buffer.committed', 'item_id': 'one'})
        await self.done('old')
        self.assertFalse(any(m['type'] == 'response.create' for m in self.sent))
        await self.agent.handle({'type': 'input_audio_buffer.committed', 'item_id': 'two'})
        await self.agent.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'two'})
        await self.agent.handle({'type': 'input_audio_buffer.committed', 'item_id': 'two'})
        await self.created('fresh')
        self.assertNotIn('fresh', self.agent.cancelled)
        self.assertEqual(sum(m['type'] == 'response.create' for m in self.sent), 1)

    async def test_explicit_rereport_owns_new_attempt(self):
        self.complete('result')
        await self.agent.request_response()
        await self.created('silent')
        await self.done('silent')
        await self.agent.report_task('result')
        await self.created('rereport')
        await self.audio_item('rereport', 'new-audio')
        await self.agent.interrupt()
        self.assertEqual(self.pending(), ['result'])
        self.assertEqual(self.center.status('result')['announcement']['attempt'], 2)

    async def test_server_cancel_before_speech_event_reclaims_offers(self):
        self.complete('result')
        await self.agent.request_response()
        await self.created('r')
        await self.audio_item('r', 'a')
        await self.agent.handle({'type': 'response.done', 'response': {'id': 'r', 'status': 'cancelled'}})
        self.assertEqual(self.audio.buffered, 0)
        self.assertEqual(self.pending(), ['result'])
        await self.agent.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'u'})
        await self.agent.handle({'type': 'input_audio_buffer.committed', 'item_id': 'u'})
        self.assertEqual(sum(m['type'] == 'response.create' for m in self.sent), 2)

    async def test_local_queue_cleanup_and_frozen_progress(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from sparkie.realtime_audio import RealtimeLocalAudio
        audio = RealtimeLocalAudio(echo_mode='headphones')
        audio._loop = asyncio.get_running_loop()
        audio.append_output('first', bytes([1, 0]) * 2400)
        audio.append_output('later', bytes([2, 0]) * 2400)
        audio.outputs['first'].blocks = [(10, 4800)]
        with patch('sparkie.realtime_audio.time.monotonic', return_value=10.025):
            await audio.stop_speaking()
        self.assertEqual(audio.outputs['first'].played_ms(now=100), 25)
        self.assertTrue(all(o.chunks.empty() and not o.pending for o in audio.outputs.values()))
        self.assertFalse(audio.waiting_outputs)
        audio.append_output('first', bytes(100))
        self.assertTrue(audio.outputs['first'].chunks.empty())
        audio.append_output('fresh', bytes([3, 0]) * 2)
        audio.finish_output('fresh')
        out = bytearray(4)
        audio._callback(bytes(4), out, 2,
                        SimpleNamespace(inputBufferAdcTime=0, outputBufferDacTime=0, currentTime=0),
                        SimpleNamespace(input_overflow=False, output_underflow=False))
        self.assertEqual(out, bytes([3, 0]) * 2)

    async def test_overlap_error_returns_offer_then_waits_for_existing_response(self):
        self.complete('result')
        await self.agent.request_response()
        await self.agent.handle({'type': 'error', 'error': {'code': 'conversation_already_has_active_response'}})
        self.assertEqual(self.pending(), ['result'])
        await self.agent.request_response()
        self.assertEqual(sum(m['type'] == 'response.create' for m in self.sent), 1)
        await self.created('existing')
        await self.done('existing')
        self.assertEqual(sum(m['type'] == 'response.create' for m in self.sent), 2)
        self.assertEqual(self.center.status('result')['announcement']['attempt'], 2)

    async def test_transcript_before_interrupt_and_audio_done_preserves_draft(self):
        await self.created('r')
        await self.agent.handle({'type': 'response.output_audio_transcript.delta', 'response_id': 'r',
                                 'item_id': 'early-text', 'content_index': 1, 'delta': 'Useful partial draft'})
        await self.human('t', 'start')
        await self.done('r')
        await self.human('t', 'commit', text='Change the answer')
        self.assertIn('Useful partial draft', self.sent[-2]['item']['content'][0]['text'])
        truncation = next(m for m in self.sent if m['type'] == 'conversation.item.truncate')
        self.assertEqual(truncation['content_index'], 1)
        self.assertEqual(truncation['audio_end_ms'], 0)
        # A late unseen audio item also gets exactly one cleanup after response.done.
        await self.agent.handle({'type': 'response.output_audio.delta', 'response_id': 'r',
                                 'item_id': 'late', 'delta': base64.b64encode(bytes(960)).decode()})
        self.assertNotIn('late', self.audio.outputs)
        self.assertTrue(any(m['type'] == 'conversation.item.truncate' and m['item_id'] == 'late' for m in self.sent))

    async def test_send_failure_restores_persisted_pending_obligation(self):
        self.complete('result')
        async def fail(message):
            raise RuntimeError('offline injected send failure')
        self.agent.ws.send = fail
        with self.assertRaises(RuntimeError):
            await self.agent.request_response()
        self.assertEqual(self.pending(), ['result'])
        self.assertFalse(self.agent.response_pending)
        self.assertFalse(self.agent.pending_offers)
        saved = json.loads((Path(self.directory.name) / 'tasks.json').read_text())
        self.assertEqual(saved[0]['announcement']['state'], 'pending')
