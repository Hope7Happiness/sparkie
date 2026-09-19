import asyncio
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sparkie.contracts import TranscriptEvent
from sparkie.engine import Primitive
from sparkie.simulation import SimulatedMeeting, ScriptedDeepgram, SimulatedSpeech
from sparkie.wake import addressed_request


class WakeTests(unittest.TestCase):
    def test_standalone_and_direct_address_without_punctuation(self):
        for text in ["Sparkie", "Hey Sparkie are you there?", "Sparkie你在吗？", "Sparky, summarize this.",
                     "Hi Sparky", "Hi. It's Sparkie.", "Hello, Sparkie!", "Hi, Sparky, what is a WebSocket?",
                     "Sparkie. Sparkie. Sparkie.", "Sparkie. Is a web socket?", "Hi, Sparkie. Try to",
                     "Sparkie, give me an example", "Sparkie，把刚才的结论列出来",
                     "Sparkie is our product", "Hi, Sparky is our product",
                     "Sparkie. Sparkie is our product"]:
            self.assertIsNotNone(addressed_request(text), text)

    def test_mentions_names_and_cancellation_are_not_requests(self):
        for text in ["我们讨论 Sparkie", "Sparkieville", "Sparkie，不用了", "Sparkie, never mind", "Hi, it is Sparkie who built the product.",
                     "It is Sparkie."]:
            self.assertIsNone(addressed_request(text), text)


class EngineTests(unittest.IsolatedAsyncioTestCase):
    def event(self, id, text, **kwargs):
        return TranscriptEvent("sim", str(id), int(id) * 100, text, **kwargs)

    async def test_input_continues_during_reply_and_duplicate_is_ignored(self):
        with tempfile.TemporaryDirectory() as path:
            events = [self.event(1, "Sparkie"), self.event(1, "Sparkie"), self.event(2, "我们继续讨论"),
                      self.event(3, "Sparkie", source="bot")]
            meeting = SimulatedMeeting(events, Path(path), interval=.01, playback=.1)
            engine = Primitive(meeting, ScriptedDeepgram(events), SimulatedSpeech())
            result = await engine.run()
            self.assertEqual(sum(e["type"] == "wake" for e in result["events"]), 1)
            self.assertGreater(meeting.inputs_while_playing, 0)
            self.assertFalse(meeting.joined)

    async def test_question_ack_is_cached_and_selected_without_extra_inference(self):
        from unittest.mock import AsyncMock
        with tempfile.TemporaryDirectory() as path:
            events = [self.event(1, "Sparkie"), self.event(2, "Sparkie, try to explain sockets."),
                      self.event(3, "Sparkie, give me an example.")]
            meeting = SimulatedMeeting(events, Path(path), interval=.01, playback=0)
            brain = AsyncMock(answer=AsyncMock(return_value="A short answer."))
            mouth = AsyncMock(synthesize=AsyncMock(side_effect=lambda text: text.encode()))
            engine = Primitive(meeting, ScriptedDeepgram(events), mouth, reply="I'm here.", brain=brain)
            result = await engine.run()
            replies = [e['text'] for e in result['events'] if e['type'] == 'reply']
            self.assertEqual(replies, ["I'm here.", "Let me think for a moment.", "Let me think for a moment."])
            self.assertEqual(brain.answer.await_count, 2)
            calls = [call.args[0] for call in mouth.synthesize.await_args_list]
            self.assertEqual(calls.count("Let me think for a moment."), 1)
            self.assertEqual(calls.count("I'm here."), 1)
            self.assertEqual(engine.question_audio, b"Let me think for a moment.")

    async def test_cancel_stops_reply(self):
        with tempfile.TemporaryDirectory() as path:
            events = [self.event(1, "Sparkie"), self.event(2, "Sparkie，不用了")]
            meeting = SimulatedMeeting(events, Path(path), interval=.01, playback=10)
            result = await asyncio.wait_for(Primitive(meeting, ScriptedDeepgram(events), SimulatedSpeech()).run(), .5)
            self.assertIn("response_cancelled", [e["type"] for e in result["events"]])
            self.assertFalse(meeting.playing)

    async def test_tts_failure_prevents_join(self):
        class BrokenMouth:
            async def synthesize(self, text):
                raise RuntimeError("provider unavailable")
        with tempfile.TemporaryDirectory() as path:
            meeting = SimulatedMeeting([], Path(path))
            with self.assertRaises(RuntimeError):
                await Primitive(meeting, ScriptedDeepgram([]), BrokenMouth()).run()
            self.assertFalse(meeting.joined)

    async def test_playback_failure_is_recorded_and_meeting_leaves(self):
        class BrokenMeeting(SimulatedMeeting):
            async def play_audio(self, pcm, sample_rate):
                raise RuntimeError("playback unavailable")
        with tempfile.TemporaryDirectory() as path:
            events = [self.event(1, "Sparkie")]
            meeting = BrokenMeeting(events, Path(path), interval=0)
            result = await Primitive(meeting, ScriptedDeepgram(events), SimulatedSpeech()).run()
            self.assertEqual(result["response_failures"], 1)
            self.assertFalse(meeting.joined)

    async def test_brain_gets_snapshot_with_previous_context(self):
        class Brain:
            async def answer(self, transcript):
                self.context = transcript
                return "模拟回答"
        with tempfile.TemporaryDirectory() as path:
            events = [self.event(1, "决定先演示入会"), self.event(2, "Sparkie，总结一下")]
            meeting = SimulatedMeeting(events, Path(path), interval=0, playback=0)
            brain = Brain()
            await Primitive(meeting, ScriptedDeepgram(events), SimulatedSpeech(), brain=brain).run()
            self.assertEqual(brain.context, [e.text for e in events])

class QuestionAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_inference_overlaps_ack_and_snapshot_is_stable(self):
        from unittest.mock import AsyncMock
        brain_started = asyncio.Event()
        release = asyncio.Event()
        received = []
        class Brain:
            async def answer(self, snapshot):
                received.extend(snapshot)
                brain_started.set()
                await release.wait()
                return 'We chose Zoom.'
        class Meeting:
            async def play_audio(self, pcm, rate):
                if pcm == b'ack':
                    await asyncio.wait_for(brain_started.wait(), .5)
            async def stop_speaking(self):
                pass
        engine = Primitive(Meeting(), None, AsyncMock(synthesize=AsyncMock(return_value=b'answer')), brain=Brain())
        await engine.accept(TranscriptEvent('m', '1', 0, 'We chose Zoom.'), b'ack')
        await engine.accept(TranscriptEvent('m', '2', 100, 'Sparkie, what did we choose?'), b'ack')
        await brain_started.wait()
        await engine.accept(TranscriptEvent('m', '3', 200, 'And we will try Deepgram.'), b'ack')
        await engine.accept(TranscriptEvent('m', '4', 300, 'Sparkie, explain that.'), b'ack')
        self.assertEqual(received, ['We chose Zoom.', 'Sparkie, what did we choose?'])
        self.assertIn('And we will try Deepgram.', engine.context)
        self.assertTrue(any(e.get('reason') == 'response_busy' for e in engine.events))
        release.set()
        await engine.response_task
        self.assertTrue(any(e['type'] == 'answer' and e['response_id'] == '2' for e in engine.events))

    async def test_answer_is_visible_before_tts_failure_and_is_in_followup_context(self):
        from unittest.mock import AsyncMock
        brain = AsyncMock(answer=AsyncMock(return_value='Zoom and Deepgram.'))
        mouth = AsyncMock(synthesize=AsyncMock(side_effect=RuntimeError('secret provider body')))
        meeting = AsyncMock()
        engine = Primitive(meeting, None, mouth, brain=brain)
        await engine.accept(TranscriptEvent('m', '1', 0, 'Sparkie, what did we choose?'), b'ack')
        await engine.response_task
        types = [e['type'] for e in engine.events]
        self.assertLess(types.index('answer'), types.index('response_failed'))
        self.assertEqual(engine.events[-1]['phase'], 'answer_synthesis')
        self.assertNotIn('secret provider body', str(engine.events))
        mouth.synthesize.side_effect = None
        mouth.synthesize.return_value = b'pcm'
        await engine.accept(TranscriptEvent('m', '2', 100, 'Sparkie, explain the second one.'), b'ack')
        await engine.response_task
        self.assertTrue(any('Sparkie answer' in item and 'Zoom and Deepgram.' in item for item in brain.answer.call_args.args[0]))

    async def test_bare_wake_does_not_invoke_reasoning_and_new_session_has_no_memory(self):
        from unittest.mock import AsyncMock
        brain = AsyncMock()
        engine = Primitive(AsyncMock(), None, AsyncMock(), brain=brain)
        await engine.accept(TranscriptEvent('m', '1', 0, 'Sparkie'), b'ack')
        await engine.response_task
        brain.answer.assert_not_called()
        self.assertFalse(next(e for e in engine.events if e['type'] == 'wake')['answer_requested'])
        self.assertEqual(list(Primitive(AsyncMock(), None, AsyncMock(), brain=brain).context), [])

    async def test_cancel_during_reasoning_awaits_worker_cleanup(self):
        from unittest.mock import AsyncMock
        started, cancelled = asyncio.Event(), asyncio.Event()
        class Brain:
            async def answer(self, snapshot):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        engine = Primitive(AsyncMock(), None, AsyncMock(), brain=Brain())
        await engine.accept(TranscriptEvent('m', '1', 0, 'Sparkie, explain WebSockets.'), b'ack')
        await started.wait()
        await engine.cancel_response()
        self.assertTrue(cancelled.is_set())
        self.assertNotIn('answer', [e['type'] for e in engine.events])

    async def test_ack_and_answer_timing_have_separate_phases(self):
        import time
        from unittest.mock import AsyncMock
        class Meeting:
            timing_reliable = True
            audio_origin = time.monotonic() - 1
            async def play_audio(self, pcm, rate):
                self.last_playback_started_at = time.monotonic()
        engine = Primitive(Meeting(), None, AsyncMock(synthesize=AsyncMock(return_value=b'answer')),
                           brain=AsyncMock(answer=AsyncMock(return_value='A persistent connection.')))
        await engine.accept(TranscriptEvent('m', '1', 0, 'Sparkie, what is a WebSocket?'), b'ack')
        await engine.response_task
        timing = [e for e in engine.events if e['type'] == 'playback_timing']
        self.assertEqual([e['phase'] for e in timing], ['acknowledgement', 'answer'])
        self.assertTrue(all(e['response_id'] == '1' for e in timing))
        self.assertIn('answer_completed', [e['type'] for e in engine.events])

    async def test_reported_greeting_then_later_question_still_responds(self):
        from unittest.mock import AsyncMock
        class Meeting:
            def __init__(self):
                self.plays = 0
            async def play_audio(self, pcm, rate):
                self.plays += 1
        meeting = Meeting()
        brain = AsyncMock(answer=AsyncMock(return_value='A WebSocket stays connected.'))
        engine = Primitive(meeting, None, AsyncMock(synthesize=AsyncMock(return_value=b'answer')), brain=brain)
        await engine.accept(TranscriptEvent('m', '1', 0, "Hi. It's Sparkie."), b'ack')
        await engine.response_task
        brain.answer.assert_not_called()
        self.assertEqual(meeting.plays, 1)
        await engine.accept(TranscriptEvent('m', '2', 20000, 'Sparkie. Is a web socket?'), b'ack')
        await engine.response_task
        brain.answer.assert_awaited_once()
        self.assertEqual(meeting.plays, 3)
        self.assertEqual(sum(e['type'] == 'response_completed' for e in engine.events), 2)
