import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sparkie.contracts import TranscriptEvent
from sparkie.demo import replay, should_wake


class ReplayTests(unittest.TestCase):
    def event(self, text, **kwargs):
        return TranscriptEvent("demo", "1", 0, text, **kwargs)

    def test_direct_request(self):
        self.assertTrue(should_wake(self.event("Sparkie，总结一下。")))

    def test_no_reply_to_mentions_cancellation_echo_or_partial(self):
        for event in [self.event("我们在做 Sparkie，总结功能。"),
                      self.event("Sparkie，不用了"),
                      self.event("Sparkie，回答", source="bot"),
                      self.event("Sparkie，回答", is_final=False)]:
            self.assertFalse(should_wake(event))

    def test_duplicate_final_event_does_not_repeat_reply(self):
        event = self.event("Sparkie，总结一下")
        result = replay([event, event])
        self.assertEqual(len(result["replies"]), 1)
        self.assertEqual(len(result["transcript"]), 1)
        self.assertEqual(result["action_items"], [])

    def test_partial_does_not_suppress_final(self):
        result = replay([self.event("Sparkie，总结", is_final=False), self.event("Sparkie，总结一下")])
        self.assertEqual(len(result["replies"]), 1)
