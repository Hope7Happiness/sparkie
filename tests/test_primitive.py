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
        for text in ["Sparkie", "Hey Sparkie are you there?", "Sparkie你在吗？", "Sparky, summarize this."]:
            self.assertIsNotNone(addressed_request(text), text)

    def test_mentions_names_and_cancellation_are_not_requests(self):
        for text in ["我们讨论 Sparkie", "Sparkie is our product", "Sparkieville", "Sparkie，不用了", "Sparkie, never mind"]:
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
