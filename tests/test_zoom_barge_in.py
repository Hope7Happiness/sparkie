"""Offline barge-in through real per-user routing and provider/agent adapters."""
import asyncio
import base64
import json
import struct
import tempfile
import unittest
from types import SimpleNamespace

from sparkie.audio import AudioFrame
from sparkie.contracts import SpeechActivity, TranscriptEvent
from sparkie.participant_stt import ParticipantEars
from sparkie.providers import DeepgramEars
from sparkie.realtime import RealtimeAgent
from sparkie.realtime_zoom_audio import PCMResampler, RealtimeZoomAudio
from sparkie.task_center import TaskCenter, TranscriptLedger
from sparkie.zoom_output import ZoomOutputPolicy
from test_semantic_interruption import Bridge
from test_providers import message


class ZoomBargeInTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.events, self.sent = [], []
        emit = lambda kind, **fields: self.events.append((kind, fields))
        self.bridge = Bridge()
        self.audio = RealtimeZoomAudio(self.bridge, on_event=emit)
        self.audio.participant_transcription = True
        self.policy = ZoomOutputPolicy(self.audio, emit)
        self.center = TaskCenter(TranscriptLedger(temp.name), None, emit)
        self.agent = RealtimeAgent('unused', self.audio, self.center, emit, output_policy=self.policy)
        async def send(raw): self.sent.append(json.loads(raw))
        self.agent.ws = SimpleNamespace(send=send)
        await self.audio.join()
        self.addAsyncCleanup(self.audio.leave)
        self.addAsyncCleanup(self.center.close)

    def creates(self):
        return sum(m['type'] == 'response.create' for m in self.sent)

    async def transcript(self, text, ident='turn', speaker='zoom:10'):
        await self.agent.human_transcript(dict(text=text, event_id=ident, meeting_id='m',
                                              is_final=True, source='human', speaker_id=speaker))

    async def activity(self, phase, stream='zoom:10:1'):
        await self.agent.participant_speech(SpeechActivity(phase, 1000, stream.rsplit(':', 1)[0], stream))

    async def created(self, rid):
        await self.agent.handle({'type': 'response.created', 'response': {'id': rid}})

    async def done(self, rid):
        await self.agent.handle({'type': 'response.done', 'response': {'id': rid, 'status': 'cancelled'}})

    async def delta(self, rid, item):
        await self.agent.handle({'type': 'response.output_audio.delta', 'response_id': rid,
                                'item_id': item, 'delta': base64.b64encode(b'\x01\0' * 4800).decode()})

    async def playing(self):
        await self.transcript('Sparkie, explain the plan.', 'first')
        await self.created('old')
        await self.delta('old', 'old-audio')
        await asyncio.wait_for(self.bridge.entered.wait(), 1)

    async def test_self_filtered_interim_speech_stops_before_final_but_vad_alone_does_not(self):
        await self.playing()
        messages, frames = asyncio.Queue(), asyncio.Queue()
        connections = []
        class Socket:
            async def __aenter__(self): connections.append(True); return self
            async def __aexit__(self, *args): pass
            async def send(self, raw): pass
            def __aiter__(self): return self
            async def __anext__(self): return json.dumps(await messages.get())
        async def source():
            while True: yield await frames.get()
        router = ParticipantEars(lambda: DeepgramEars('unused', 'm', connector=lambda *a: Socket()),
                                 is_self=lambda ident: ident == 'zoom:99', speech_events=True)
        stream = router.transcribe(source())
        pending = asyncio.create_task(anext(stream))
        try:
            await frames.put(AudioFrame(1, b'\x01\0' * 640, speaker_id='zoom:99', timestamp_ms=1000))
            for _ in range(10): await asyncio.sleep(0)
            self.assertFalse(connections)
            self.assertEqual(self.bridge.cancelled, 0)
            await frames.put(AudioFrame(2, b'\x01\0' * 640, speaker_id='zoom:10', timestamp_ms=1000))
            await messages.put({'type': 'SpeechStarted', 'timestamp': 0, 'channel': [0]})
            start = await asyncio.wait_for(pending, 1)
            await self.agent.participant_speech(start)
            self.assertEqual(self.bridge.cancelled, 0)
            self.assertIsNotNone(self.policy.chain)
            await messages.put(message('Sparkie', final=False, end=False))
            confirmed = await asyncio.wait_for(anext(stream), 1)
            await self.agent.participant_speech(confirmed)
            self.assertEqual(self.bridge.cancelled, 1)
            self.assertEqual(self.audio.buffered, 0)
            self.assertTrue(self.audio.outputs['old-audio'].cancelled.is_set())
            self.assertEqual(self.creates(), 1)
            # No final transcription was available when playback stopped.
            await self.delta('old', 'late-audio')
            self.assertNotIn('late-audio', self.audio.outputs)
            await self.done('old')
            await messages.put(message('Sparkie, just give the conclusion.'))
            final = await asyncio.wait_for(anext(stream), 1)
            self.assertIsInstance(final, TranscriptEvent)
            await self.agent.human_transcript(vars(final))
            self.assertEqual(self.creates(), 1)  # Wait for utterance end.
            await self.agent.participant_speech(await asyncio.wait_for(anext(stream), 1))
            self.assertEqual(self.creates(), 2)
            self.bridge.release.set()
            await self.created('new')
            await self.delta('new', 'fresh-audio')
            await self.agent.handle({'type': 'response.output_audio.done', 'response_id': 'new', 'item_id': 'fresh-audio'})
            async with asyncio.timeout(1):
                while not self.audio.outputs['fresh-audio'].drained: await asyncio.sleep(0)
            self.assertFalse(self.audio.outputs['fresh-audio'].cancelled.is_set())
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await stream.aclose()

    async def test_interrupted_task_announcement_retries_without_a_new_completion_event(self):
        job = {'task_id': 'eligible', 'status': 'completed', 'result': 'Verified result'}
        self.center.jobs['eligible'] = job
        self.center._save(job)
        self.policy.task_ids.add('eligible')
        self.agent.ready.set()
        notifier = asyncio.create_task(self.agent.notify_tasks())
        try:
            async with asyncio.timeout(1):
                while self.creates() == 0: await asyncio.sleep(.01)
            await self.created('notice')
            await self.delta('notice', 'result')
            await asyncio.wait_for(self.bridge.entered.wait(), 1)
            await self.activity('started')
            self.assertEqual(job['announcement']['state'], 'pending')
            self.assertTrue(self.center.notifications.empty())
            await self.transcript('We are discussing the options.', 'discussion')
            await self.activity('stopped')
            await self.done('notice')
            self.agent.last_user_stop = 0
            async with asyncio.timeout(1):
                while self.creates() < 2: await asyncio.sleep(.01)
            self.assertEqual(job['announcement']['attempt'], 2)
            self.assertFalse(self.policy.notifications_paused)
        finally:
            notifier.cancel()
            await asyncio.gather(notifier, return_exceptions=True)

    async def test_completion_after_ack_interruption_is_not_permanently_muted(self):
        await self.playing()
        await self.activity('started')
        await self.transcript('I am talking to another participant.', 'ordinary')
        await self.activity('stopped')
        await self.done('old')
        job = {'task_id': 'eligible', 'status': 'failed', 'error_type': 'ExampleError'}
        self.center.jobs['eligible'] = job
        self.center._save(job)
        self.policy.task_ids.add('eligible')
        self.agent.ready.set()
        self.agent.last_user_stop = 0
        notifier = asyncio.create_task(self.agent.notify_tasks())
        try:
            async with asyncio.timeout(1):
                while self.creates() < 2: await asyncio.sleep(.01)
            self.assertEqual(job['announcement']['state'], 'offered')
        finally:
            notifier.cancel()
            await asyncio.gather(notifier, return_exceptions=True)

    async def test_ordinary_barge_in_stops_without_reopening_and_preserves_context_once(self):
        await self.playing()
        await self.activity('started')
        await self.transcript('Let us discuss this ourselves.', 'ordinary')
        await self.activity('stopped')
        await self.done('old')
        await self.transcript('Let us discuss this ourselves.', 'ordinary')
        self.assertEqual(self.creates(), 1)
        self.assertIsNone(self.policy.chain)
        texts = [m['item']['content'][0]['text'] for m in self.sent
                 if m['type'] == 'conversation.item.create' and m['item']['role'] == 'user']
        self.assertEqual(texts.count('Let us discuss this ourselves.'), 1)
        await self.agent.append(AudioFrame(0, b'\x01\0' * 240, 24000))
        self.assertFalse(any(base64.b64decode(self.sent[-1]['audio'])))

    async def test_overlap_waits_for_both_people_and_late_mixed_events_cannot_end_turn(self):
        await self.activity('started', 'zoom:10:1')
        await self.activity('started', 'zoom:20:2')
        await self.transcript('Sparkie, answer this.', 'wake')
        await self.activity('stopped', 'zoom:10:1')
        for event in ('speech_started', 'speech_stopped', 'committed'):
            await self.agent.handle({'type': 'input_audio_buffer.' + event, 'item_id': 'mixed'})
        self.assertTrue(self.agent.user_speaking)
        self.assertEqual(self.creates(), 0)
        await self.activity('stopped', 'zoom:20:2')
        self.assertEqual(self.creates(), 1)
        await self.activity('stopped', 'zoom:20:2')
        self.assertEqual(self.creates(), 1)

    async def test_unmute_survives_start_cancel_stays_closed_and_later_wake_reopens(self):
        await self.agent.control({'action': 'unmute'})
        await self.activity('started')
        await self.transcript('Give me the summary.', 'manual')
        await self.activity('stopped')
        self.assertEqual(self.creates(), 1)
        await self.created('manual')
        await self.activity('started')
        await self.transcript('Sparkie, stop', 'cancel')
        await self.activity('stopped')
        await self.done('manual')
        self.assertEqual(self.creates(), 1)
        self.assertIsNone(self.policy.chain)
        await self.activity('started')
        await self.transcript('Sparkie, try again.', 'wake')
        await self.activity('stopped')
        self.assertEqual(self.creates(), 2)

    async def test_provider_failure_cancels_output_and_keeps_task_results_pending(self):
        await self.playing()
        self.center.jobs['job'] = {'task_id': 'job', 'status': 'running'}
        await self.agent.participant_input_failed()
        self.assertEqual(self.bridge.cancelled, 1)
        self.assertEqual(self.center.jobs['job']['status'], 'running')
        self.assertIsNone(self.policy.chain)
        self.assertFalse(self.agent.notification_ready())
        self.assertTrue(any(kind == 'zoom_barge_in_unavailable' for kind, _ in self.events))

    async def test_speech_without_words_releases_turn_without_fabricating_request(self):
        await self.activity('started')
        await self.activity('stopped')
        self.assertFalse(self.agent.user_speaking)
        self.assertFalse(self.agent.awaiting_turn)
        self.assertEqual(self.creates(), 0)

    async def test_noise_candidates_cannot_cancel_playback_or_block_a_real_speaker(self):
        await self.playing()
        for _ in range(3):
            await self.activity('candidate', 'zoom:20:noise')
            await self.activity('stopped', 'zoom:20:noise')
        self.assertEqual(self.bridge.cancelled, 0)
        self.assertIsNotNone(self.policy.chain)
        self.assertFalse(self.agent.user_speaking)
        await self.activity('started')
        self.assertEqual(self.bridge.cancelled, 1)
        await self.activity('candidate', 'zoom:20:noise')
        await self.transcript('Hey Sparky, summarize.', 'new-wake')
        await self.activity('stopped')
        await self.done('old')
        self.assertEqual(self.creates(), 2)
        self.assertFalse(self.policy.notifications_paused)

    async def test_unconfirmed_noise_resumes_remaining_pcm_after_350ms_without_regenerating(self):
        await self.transcript('Hey Sparky, explain.', 'wake')
        await self.created('old')
        pcm = b''.join(struct.pack('<h', i - 2400) for i in range(4800))
        await self.agent.handle({'type': 'response.output_audio.delta', 'response_id': 'old',
            'item_id': 'old-audio', 'delta': base64.b64encode(pcm).decode()})
        await asyncio.wait_for(self.bridge.entered.wait(), 1)
        await self.agent.handle({'type': 'response.output_audio.done',
                                'response_id': 'old', 'item_id': 'old-audio'})
        await self.activity('candidate')
        self.assertTrue(self.audio.paused_for_candidate)
        self.bridge.release.set()
        await asyncio.sleep(.2)
        self.assertEqual(len(self.bridge.packets), 1)
        self.assertFalse(self.audio.outputs['old-audio'].drained)
        # A second VAD pulse cannot keep extending the confirmation deadline.
        await self.activity('candidate', 'zoom:20:noise')
        await asyncio.sleep(.2)
        self.assertFalse(self.audio.paused_for_candidate)
        self.assertTrue(self.audio.outputs['old-audio'].drained)
        self.assertEqual(len(b''.join(self.bridge.packets)), 12800)
        self.assertEqual(b''.join(self.bridge.packets), PCMResampler(24000, 32000).feed(pcm, final=True))
        self.assertEqual(self.bridge.cancelled, 0)
        self.assertEqual(self.creates(), 1)
        self.assertFalse(any(m['type'] in ('response.cancel', 'conversation.item.truncate') for m in self.sent))
        self.assertEqual(sum(k == 'zoom_barge_in_false_alarm' for k, _ in self.events), 1)

    async def test_confirmed_speech_or_explicit_mute_cancels_resume_timer(self):
        for explicit in (False, True):
            with self.subTest(explicit=explicit):
                # Each case owns a fresh response and packet.
                await self.transcript('Hey Sparky, explain.', 'wake-' + str(explicit))
                rid = 'r-' + str(explicit)
                await self.created(rid)
                await self.delta(rid, rid)
                await self.activity('candidate')
                self.assertIsNotNone(self.agent.candidate_pause_timer)
                if explicit:
                    await self.agent.control({'action': 'mute'})
                else:
                    await self.activity('started')
                    await self.activity('stopped')
                self.assertIsNone(self.agent.candidate_pause_timer)
                await self.done(rid)
                packets = len(self.bridge.packets)
                await asyncio.sleep(.4)
                self.assertEqual(len(self.bridge.packets), packets)
                self.assertTrue(self.audio.outputs[rid].cancelled.is_set())
        self.assertFalse(any(k == 'zoom_barge_in_false_alarm' for k, _ in self.events))

    async def test_late_confirmed_speech_still_interrupts_after_false_alarm_resume(self):
        await self.playing()
        await self.activity('candidate')
        await asyncio.sleep(.4)
        self.assertFalse(self.audio.paused_for_candidate)
        await self.activity('started')
        self.assertTrue(self.audio.outputs['old-audio'].cancelled.is_set())
        self.assertEqual(self.bridge.cancelled, 1)

    async def test_idle_discussion_defers_task_notification_until_speech_ends_without_dismissing_it(self):
        job = {'task_id': 'eligible', 'status': 'completed', 'result': 'Verified offline result'}
        self.center.jobs['eligible'] = job
        self.center._save(job)
        self.policy.task_ids.add('eligible')
        self.agent.ready.set()
        await self.activity('started')
        self.center.notifications.put_nowait(job)
        notifier = asyncio.create_task(self.agent.notify_tasks())
        try:
            await asyncio.sleep(.02)
            self.assertEqual(self.creates(), 0)
            await self.transcript('We are discussing the options.', 'discussion')
            await self.activity('stopped')
            async with asyncio.timeout(2):
                while self.creates() == 0: await asyncio.sleep(.01)
            self.assertEqual(self.creates(), 1)
            self.assertEqual(job['announcement']['state'], 'offered')
            await self.created('notification')
            await self.agent.control({'action': 'mute'})
            await self.activity('started')
            await self.activity('stopped')
            self.assertTrue(self.policy.notifications_paused)
            self.assertEqual(job['announcement']['state'], 'pending')
        finally:
            notifier.cancel()
            await asyncio.gather(notifier, return_exceptions=True)
