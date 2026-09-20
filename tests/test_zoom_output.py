"""Zoom-only mute MVP: fake bridge/WS/worker, no external services."""
import asyncio
import base64
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sparkie.audio import AudioFrame
from sparkie.browser_audio import BrowserAudio
from sparkie.realtime import RealtimeAgent
from sparkie.realtime_zoom_audio import RealtimeZoomAudio
from sparkie.task_center import TaskCenter, TranscriptLedger
from sparkie.zoom_output import ZoomOutputPolicy
from test_semantic_interruption import Bridge


class ZoomOutputTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.events, self.sent = [], []
        self.emit = lambda k, **v: self.events.append((k, v))
        self.bridge = Bridge()
        self.audio = RealtimeZoomAudio(self.bridge, on_event=self.emit)
        self.policy = ZoomOutputPolicy(self.audio, self.emit)
        self.worker_release = asyncio.Event()
        release = self.worker_release
        class Worker:
            async def run(self, *args):
                await release.wait()
                return 'Verified offline result'
        self.center = TaskCenter(TranscriptLedger(self.temp.name), Worker(), self.emit)
        self.agent = RealtimeAgent('unused', self.audio, self.center, self.emit, output_policy=self.policy)
        async def send(message): self.sent.append(json.loads(message))
        self.agent.ws = SimpleNamespace(send=send)
        await self.audio.join()
        self.addAsyncCleanup(self.audio.leave)
        self.addAsyncCleanup(self.center.close)

    async def transcript(self, text, ident='t', **kwargs):
        await self.agent.human_transcript(dict(text=text, event_id=ident, meeting_id='meeting',
                                              is_final=True, source='human', **kwargs))

    async def created(self, rid):
        await self.agent.handle({'type': 'response.created', 'response': {'id': rid}})

    async def done(self, rid):
        await self.agent.handle({'type': 'response.done', 'response': {'id': rid, 'status': 'completed'}})

    async def delta(self, rid, item, pcm=bytes(9600)):
        await self.agent.handle({'type': 'response.output_audio.delta', 'response_id': rid,
                                 'item_id': item, 'delta': base64.b64encode(pcm).decode()})

    async def finish(self, rid, item):
        await self.agent.handle({'type': 'response.output_audio.done', 'response_id': rid, 'item_id': item})

    async def drain(self, item):
        async with asyncio.timeout(1):
            while not self.audio.outputs[item].drained:
                await asyncio.sleep(0)

    async def test_muted_input_continues_and_unexpected_audio_is_unheard(self):
        await self.agent.append(AudioFrame(0, bytes([1, 0]) * 240, 24000))
        self.assertTrue(any(base64.b64decode(self.sent[-1]['audio'])))
        await self.agent.handle({'type': 'input_audio_buffer.committed', 'item_id': 'human'})
        await self.transcript('We should discuss architecture')
        self.assertFalse(any(m['type'] == 'response.create' for m in self.sent))
        self.audio.append_output('direct-bypass', bytes(9600))
        await self.created('unexpected')
        await self.delta('unexpected', 'muted')
        await self.agent.handle({'type': 'response.output_audio_transcript.done', 'response_id': 'unexpected',
                                 'item_id': 'muted', 'transcript': 'Unheard draft'})
        await self.finish('unexpected', 'muted')
        await self.done('unexpected')
        self.assertFalse(self.audio.outputs)
        self.assertEqual(self.bridge.packets, [])
        self.assertTrue(any(m['type'] == 'conversation.item.truncate' and m['audio_end_ms'] == 0 for m in self.sent))
        self.assertEqual(self.agent.recovery['muted']['delivery_confirmed'], False)

    async def test_direct_local_tasks_keep_provenance_and_pending_delivery(self):
        await self.transcript('Hey Sparkie, create a file and open the requested page')
        await self.created('actions')
        with patch('sparkie.task_center.run_local_action', new=AsyncMock(return_value='Verified local result')):
            for name, arguments in [('create_desktop_file', {'filename': 'test.txt', 'content': 'test'}),
                                    ('open_website', {'url': 'https://example.com'})]:
                await self.agent.handle({'type': 'response.function_call_arguments.done',
                    'response_id': 'actions', 'call_id': name, 'name': name,
                    'arguments': json.dumps(arguments)})
            await asyncio.gather(*self.center.runners.values())
        ids = list(self.center.jobs)
        self.assertEqual(set(ids), self.policy.task_ids)
        self.assertEqual([j['task_id'] for j in self.agent.pending_announcements()], ids)
        persisted = json.loads((self.center.ledger.directory / 'tasks.json').read_text())
        self.assertTrue(all(j['zoom_output_origin'] == 'addressed_turn' for j in persisted))
        offers = self.center.offer_announcements(ids)
        self.center.confirm_announcement(**offers[0])
        self.center.defer_announcements(offers)
        self.assertEqual([j['task_id'] for j in self.agent.pending_announcements()], ids[1:])

    async def test_wake_long_reply_continuation_and_auto_close(self):
        await self.transcript('Hey Sparkie, explain in detail')
        await self.created('one')
        self.bridge.release.set()
        await self.delta('one', 'a')
        await self.finish('one', 'a')
        await self.agent.handle({'type': 'response.function_call_arguments.done', 'response_id': 'one',
                                 'call_id': 'c', 'name': 'task_status', 'arguments': '{"task_id":"missing"}'})
        await self.done('one')
        self.assertIsNotNone(self.policy.chain)
        await self.created('two')
        # More than 120 seconds cumulatively, in short drained batches. No wall-clock wait.
        for _ in range(130):
            await self.delta('two', 'long', bytes(48000))
            async with asyncio.timeout(1):
                while self.audio.buffered >= self.audio.PACKET_BYTES or self.audio.play_task:
                    await asyncio.sleep(0)
        await self.finish('two', 'long')
        await self.done('two')
        await self.drain('long')
        self.assertGreater(self.audio.outputs['long'].generated, 48000 * 120)
        self.assertIsNone(self.policy.chain)
        self.assertEqual(self.agent.cancelled, set())
        count = len(self.bridge.packets)
        await self.delta('two', 'late')
        self.assertNotIn('late', self.audio.outputs)
        self.assertEqual(len(self.bridge.packets), count)

    async def test_manual_mute_clears_all_and_unmute_only_arms_next_turn(self):
        await self.transcript('Hi Sparky, explain')
        await self.created('r')
        await self.delta('r', 'playing')
        await self.delta('r', 'queued')
        await asyncio.wait_for(self.bridge.entered.wait(), .5)
        await self.agent.control({'action': 'mute'})
        self.assertEqual(self.audio.buffered, 0)
        self.assertFalse(self.audio.waiting)
        self.assertEqual(self.bridge.cancelled, 1)
        await self.agent.control({'action': 'unmute'})
        await self.delta('r', 'stale')
        self.assertNotIn('stale', self.audio.outputs)
        await self.done('r')
        self.assertIsNone(self.policy.chain)
        await self.transcript('Now explain the alternative', 'next')
        self.assertIsNotNone(self.policy.chain)
        self.assertEqual(sum(m['type'] == 'response.create' for m in self.sent), 2)

    async def test_task_provenance_notification_and_dismissal_preserve_jobs(self):
        unrelated = self.center.submit('unrelated task')['task_id']
        await self.transcript('Sparkie, research this')
        await self.created('r')
        await self.agent.handle({'type': 'response.function_call_arguments.done', 'response_id': 'r',
                                 'call_id': 'delegate', 'name': 'delegate_task', 'arguments': '{"request":"research"}'})
        owned = next(t for t in self.center.jobs if t != unrelated)
        self.assertIn(owned, self.policy.task_ids)
        self.assertEqual(self.center.jobs[owned]['zoom_output_origin'], 'addressed_turn')
        await self.done('r')
        await self.created('ack')
        await self.done('ack')
        self.worker_release.set()
        await asyncio.gather(*self.center.runners.values())
        self.agent.last_user_stop = 0
        self.agent.ready.set()
        notifier = asyncio.create_task(self.agent.notify_tasks())
        try:
            async with asyncio.timeout(.5):
                while not self.agent.response_pending:
                    await asyncio.sleep(0)
            await self.created('notice')
            self.assertEqual([o['task_id'] for o in self.agent.response_offers['notice']], [owned])
            self.assertEqual(self.center.status(unrelated)['announcement']['state'], 'pending')
            await self.delta('notice', 'result')
            await self.transcript('Sparkie, stop', 'stop')
            self.assertIsNone(self.policy.chain)
            self.assertEqual(self.center.status(owned)['announcement']['state'], 'pending')
            self.assertTrue(all(j['status'] == 'completed' for j in self.center.jobs.values()))
            self.assertTrue(self.policy.notifications_paused)
        finally:
            notifier.cancel()
            await asyncio.gather(notifier, return_exceptions=True)

    async def test_late_created_and_vad_cannot_steal_new_wake(self):
        await self.transcript('Sparkie, first', 'first')
        await self.agent.control({'action': 'mute'})
        await self.transcript('Sparkie, second', 'second')
        await self.created('old')
        await self.delta('old', 'old-audio')
        self.assertNotIn('old-audio', self.audio.outputs)
        await self.done('old')
        await self.created('new')
        await self.agent.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'late-vad'})
        await self.agent.handle({'type': 'input_audio_buffer.committed', 'item_id': 'late-vad'})
        await self.delta('new', 'new-audio')
        self.assertIn('new-audio', self.audio.outputs)
        self.assertEqual(sum(m['type'] == 'response.create' for m in self.sent), 2)
        await self.transcript('Sparkie, second', 'second')
        self.assertNotIn('new', self.agent.cancelled)

    async def test_wake_rules_external_controls_restart_and_browser_scope(self):
        for text in ('Hey Sparkie, hello', 'Hi Sparky', 'Sparkie解释一下'):
            self.assertEqual(self.policy.decision(text), 'wake')
        for text in ('Sparkie, stop', '不用了', 'never mind'):
            self.assertEqual(self.policy.decision(text), 'mute')
        self.assertEqual(self.policy.decision('We discussed Sparkie yesterday'), 'ignore')
        await self.agent.control({'action': 'human_turn', 'source': 'human', 'turn_id': 'external', 'phase': 'start'})
        await self.agent.control({'action': 'human_turn', 'source': 'human', 'turn_id': 'external', 'phase': 'commit',
                                  'text': 'Hey Sparkie, answer'})
        self.assertIsNotNone(self.policy.chain)
        restarted = ZoomOutputPolicy(RealtimeZoomAudio(Bridge(), on_event=self.emit), self.emit)
        self.assertIsNone(restarted.chain)
        browser = BrowserAudio(max_seconds=10, on_event=self.emit)
        agent = RealtimeAgent('unused', browser, self.center, self.emit)
        agent.ws = self.agent.ws
        await agent.handle({'type': 'input_audio_buffer.committed', 'item_id': 'ordinary'})
        self.assertTrue(agent.response_pending)
        with self.assertRaises(ValueError):
            await agent.control({'action': 'mute'})

    async def test_generation_done_waits_for_actual_queue_drain(self):
        await self.transcript('Hello Sparkie, respond')
        await self.created('r')
        await self.delta('r', 'queued')
        await self.finish('r', 'queued')
        await asyncio.wait_for(self.bridge.entered.wait(), .5)
        await self.done('r')
        self.assertIsNotNone(self.policy.chain)
        self.bridge.release.set()
        await self.drain('queued')
        self.assertIsNone(self.policy.chain)
        self.assertFalse(self.policy.notifications_paused)

    async def test_muting_does_not_cancel_running_worker_or_accept_bot_wake(self):
        task_id = self.center.submit('keep working')['task_id']
        await asyncio.sleep(0)
        await self.agent.human_transcript({'source': 'bot', 'is_final': True, 'event_id': 'bot',
                                           'text': 'Hey Sparkie, speak'})
        await self.agent.human_transcript({'source': 'human', 'is_final': False, 'event_id': 'partial',
                                           'text': 'Hey Sparkie, speak'})
        self.assertIsNone(self.policy.chain)
        await self.agent.control({'action': 'mute'})
        self.assertFalse(self.center.runners[task_id].done())
        self.worker_release.set()
        await self.center.runners[task_id]
        self.assertEqual(self.center.status(task_id)['status'], 'completed')
        self.assertEqual(self.agent.pending_announcements(), [])
