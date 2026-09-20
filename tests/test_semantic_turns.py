"""Semantic boundaries and late final words, with no external services."""
import asyncio
import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import test_zoom_barge_in as zoom_fixture

from sparkie.audio import AudioFrame
from sparkie.contracts import SpeechActivity, TranscriptEvent
from sparkie.participant_stt import ParticipantEars
from sparkie.providers import ProviderError
from sparkie.semantic_turns import SemanticTurnBuffer, SemanticTurnEars, semantic_session_config


def result(text, start=0, duration=1, final=True, speech_final=True):
    tokens = text.split()
    return {'type': 'Results', 'start': start, 'duration': duration, 'is_final': final,
            'speech_final': speech_final, 'channel': {'alternatives': [{
                'transcript': text, 'words': [
                    {'word': token, 'punctuated_word': token,
                     'start': start + i * duration / max(1, len(tokens)),
                     'end': start + (i + .8) * duration / max(1, len(tokens))}
                    for i, token in enumerate(tokens)]}]}}


def texts(events):
    return [event.text for event in events if isinstance(event, TranscriptEvent)]


class SemanticBufferTests(unittest.TestCase):
    def test_short_pause_endpoints_accumulate_one_complete_request(self):
        buffer = SemanticTurnBuffer('meeting')
        all_events = []
        for message in [result('Hey Sparkie,', 0), result('could you check', 1.4),
                        result('the README?', 2.8)]:
            all_events += buffer.result(message)
        self.assertEqual(texts(all_events), [])
        self.assertEqual([e.phase for e in all_events], ['started'])
        self.assertEqual(texts(buffer.boundary(3800)), ['Hey Sparkie, could you check the README?'])
        self.assertEqual(buffer.boundary(3800), [])

    def test_end_waits_for_final_transcript_not_interim_or_arrival_delay(self):
        buffer = SemanticTurnBuffer('meeting')
        buffer.result(result('Hey Sparkie, check the wrong file', duration=2, final=False))
        self.assertEqual(buffer.boundary(2000), [])
        self.assertEqual(texts(buffer.result(result('Hey Sparkie,', duration=1))), [])
        events = buffer.result(result('check the README.', start=1, duration=1))
        self.assertEqual(texts(events), ['Hey Sparkie, check the README.'])
        self.assertEqual(events[-1].phase, 'stopped')

    def test_cross_boundary_final_result_splits_by_word_times(self):
        buffer = SemanticTurnBuffer('meeting')
        buffer.boundary(1000)
        events = buffer.result(result('First turn Second turn', duration=2))
        self.assertEqual(texts(events), ['First turn'])
        self.assertIn(1, buffer.active)
        self.assertEqual(texts(buffer.boundary(2000)), ['Second turn'])

    def test_late_old_boundary_keeps_new_speech_active(self):
        buffer = SemanticTurnBuffer('meeting')
        buffer.result(result('First request', duration=1))
        buffer.result(result('Second request', start=1.2, duration=1, final=False))
        events = buffer.boundary(1000)
        self.assertEqual(texts(events), ['First request'])
        self.assertEqual([(e.phase, e.stream_id) for e in events if isinstance(e, SpeechActivity)],
                         [('started', '1'), ('stopped', '0')])
        self.assertEqual(buffer.active, {1})

    def test_final_replays_do_not_duplicate_words_or_restart_speech(self):
        buffer = SemanticTurnBuffer('meeting')
        message = result('Hey Sparkie')
        buffer.result(message)
        buffer.boundary(1000)
        self.assertEqual(buffer.result(message), [])
        self.assertEqual(buffer.result(result('Hey Sparkie', final=False)), [])

    def test_missing_word_timing_cannot_authorize_a_guessed_turn(self):
        buffer = SemanticTurnBuffer('meeting')
        message = result('Hey Sparkie')
        message['channel']['alternatives'][0]['words'] = []
        with self.assertRaisesRegex(ProviderError, 'missing_words'):
            buffer.result(message)

    def test_punctuation_revision_of_a_boundary_crossing_word_cannot_reopen_old_turn(self):
        buffer = SemanticTurnBuffer('meeting')
        buffer.result(result('Sparkie.', duration=1))
        buffer.boundary(500)
        self.assertEqual(buffer.result(result('Sparkie', duration=1, final=False)), [])
        self.assertEqual(buffer.result(result('Sparkie', duration=1)), [])
        self.assertFalse(buffer.active)
        self.assertFalse(texts(buffer.boundary(1000)))


class Socket:
    def __init__(self, realtime=False):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.realtime = realtime
        self.closed = False

    async def __aenter__(self): return self
    async def __aexit__(self, *args): self.closed = True

    async def send(self, raw):
        self.sent.append(raw)
        if not isinstance(raw, str): return
        message = json.loads(raw)
        if message['type'] == 'session.update':
            await self.incoming.put({'type': 'session.updated', 'session': message['session']})
        if message['type'] == 'CloseStream':
            await self.incoming.put(None)

    def __aiter__(self): return self
    async def __anext__(self):
        message = await self.incoming.get()
        if message is None: raise StopAsyncIteration
        return json.dumps(message)


class SemanticAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.dg, self.rt = Socket(), Socket(True)
        self.audio = asyncio.Queue()
        self.events, self.diagnostics = [], []
        self.ears = SemanticTurnEars('unused', 'unused', 'meeting',
                                    connector=lambda *a, **k: self.rt,
                                    dg_connector=lambda *a: self.dg, alignment_timeout=.3,
                                    on_event=lambda kind, **fields: self.diagnostics.append((kind, fields)))
        async def frames():
            while (frame := await self.audio.get()) is not None:
                yield frame
        async def collect():
            async for event in self.ears.transcribe(frames()): self.events.append(event)
        self.task = asyncio.create_task(collect())
        self.addAsyncCleanup(self.cleanup)
        await self.audio.put(AudioFrame(0, b'\x01\0' * 32000))
        await self.until(lambda: any(isinstance(x, bytes) for x in self.dg.sent))

    async def cleanup(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    async def until(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                if self.task.done(): self.task.result()
                await asyncio.sleep(.001)

    async def test_audio_reaches_detector_and_late_words_are_finalized_before_release(self):
        config = json.loads(self.rt.sent[0])
        self.assertEqual(config, semantic_session_config('gpt-realtime-2.1'))
        self.assertTrue(any(json.loads(x)['type'] == 'input_audio_buffer.append' for x in self.rt.sent))
        await self.dg.incoming.put(result('Hey Sparkie', duration=.4))
        await self.rt.incoming.put({'type': 'input_audio_buffer.speech_stopped', 'audio_end_ms': 900})
        await self.until(lambda: any(isinstance(x, str) and json.loads(x)['type'] == 'Finalize' for x in self.dg.sent))
        self.assertEqual(texts(self.events), [])
        final = result('check README.', start=.4, duration=.5)
        final['from_finalize'] = True
        await self.dg.incoming.put(final)
        await self.until(lambda: bool(texts(self.events)))
        self.assertEqual(texts(self.events), ['Hey Sparkie check README.'])
        self.assertEqual(self.events[-1].phase, 'stopped')
        await self.rt.incoming.put({'type': 'input_audio_buffer.committed', 'item_id': 'audio-1'})
        await self.until(lambda: any(json.loads(x).get('type') == 'conversation.item.delete' for x in self.rt.sent))
        await self.audio.put(None)
        await asyncio.wait_for(self.task, 1)
        self.assertTrue(self.dg.closed and self.rt.closed)

    async def test_alignment_timeout_fails_closed_instead_of_using_partial_words(self):
        await self.dg.incoming.put(result('Hey Sparkie', duration=.4))
        await self.rt.incoming.put({'type': 'input_audio_buffer.speech_stopped', 'audio_end_ms': 900})
        with self.assertRaisesRegex(ProviderError, 'alignment_timeout'):
            await asyncio.wait_for(self.task, 1)
        self.assertFalse(texts(self.events))

    async def test_provider_failure_or_premature_close_cannot_authorize(self):
        await self.dg.incoming.put(result('Hey Sparkie'))
        await self.rt.incoming.put({'type': 'error', 'error': {'message': 'private provider details'}})
        with self.assertRaisesRegex(ProviderError, '^semantic_realtime_error$'):
            await asyncio.wait_for(self.task, 1)
        self.assertFalse(texts(self.events))

    async def test_shutdown_does_not_fabricate_a_semantic_endpoint(self):
        await self.dg.incoming.put(result('Hey Sparkie'))
        await self.until(lambda: bool(self.events))
        await self.audio.put(None)
        await asyncio.wait_for(self.task, 1)
        self.assertFalse(texts(self.events))
        self.assertTrue(any(k == 'semantic_turn_discarded' for k, _ in self.diagnostics))


class SemanticParticipantTests(unittest.IsolatedAsyncioTestCase):
    async def test_sparse_callbacks_get_silence_and_keep_speaker_turn_ids_separate(self):
        received = []
        class Ears:
            async def transcribe(self, frames):
                async for frame in frames:
                    received.append(frame)
                    if len(received) == 3:
                        yield SpeechActivity('started', 0, stream_id='0')
                        yield SpeechActivity('started', 200, stream_id='1')
                        yield SpeechActivity('stopped', 100, stream_id='0')
                        return
        queue = asyncio.Queue()
        async def frames():
            while (frame := await queue.get()) is not None: yield frame
        router = ParticipantEars(Ears, continuous_silence=True, idle_seconds=15,
                                 is_self=lambda ident: ident == 'self', speech_events=True)
        events = []
        async def collect():
            async for event in router.transcribe(frames()): events.append(event)
        task = asyncio.create_task(collect())
        try:
            await queue.put(AudioFrame(0, b'\x01\0' * 640, speaker_id='self', timestamp_ms=0))
            await queue.put(AudioFrame(0, b'\x01\0' * 640, speaker_id='human', timestamp_ms=0))
            async with asyncio.timeout(1):
                while len(events) < 4: await asyncio.sleep(.01)
            self.assertTrue(all(not any(f.pcm) for f in received[1:]))
            self.assertEqual([(e.phase, e.stream_id) for e in events],
                             [('started', 'human:1:0'), ('started', 'human:1:1'),
                              ('stopped', 'human:1:0'), ('stopped', 'human:1:1')])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class SemanticAgentTests(unittest.IsolatedAsyncioTestCase):
    creates = zoom_fixture.ZoomBargeInTests.creates

    async def asyncSetUp(self):
        await zoom_fixture.ZoomBargeInTests.asyncSetUp(self)
        self.router = SimpleNamespace(model='fake', classify=AsyncMock(return_value='accept'), close=AsyncMock())
        self.agent.wake_router = self.router
        self.addAsyncCleanup(self.agent.close_wake_router)

    async def deliver(self, events):
        for event in events:
            if isinstance(event, SpeechActivity):
                await self.agent.participant_speech(replace(event, speaker_id='zoom:10',
                                                            stream_id='zoom:10:1:' + event.stream_id))
            else:
                await self.agent.human_transcript(vars(replace(event, speaker_id='zoom:10')))

    async def test_fragmented_request_causes_only_one_semantic_wake_decision_and_reply(self):
        buffer = SemanticTurnBuffer('meeting')
        await self.deliver(buffer.result(result('Hey Sparkie,', 0)))
        await self.deliver(buffer.result(result('could you check', 1.4)))
        await self.deliver(buffer.result(result('the README?', 2.8)))
        self.router.classify.assert_not_awaited()
        self.assertTrue(self.agent.user_speaking)
        self.assertEqual(self.creates(), 0)
        await self.deliver(buffer.boundary(3800))
        await asyncio.gather(*self.agent.wake_tasks)
        self.router.classify.assert_awaited_once_with('Hey Sparkie, could you check the README?')
        self.assertEqual(self.creates(), 1)
        self.assertFalse(self.agent.user_speaking)

    async def test_late_boundary_cannot_reply_over_the_same_person_next_turn(self):
        buffer = SemanticTurnBuffer('meeting')
        await self.deliver(buffer.result(result('Hey Sparkie, help.', 0)))
        await self.deliver(buffer.result(result('Actually wait.', 1.2, final=False)))
        await self.deliver(buffer.boundary(1000))
        await asyncio.gather(*self.agent.wake_tasks)
        self.assertTrue(self.agent.user_speaking)
        self.assertEqual(self.creates(), 0)
