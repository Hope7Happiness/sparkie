import unittest
from sparkie.wake import addressed_request


class WakeTests(unittest.TestCase):
    def test_standalone_and_direct_address_without_punctuation(self):
        for text in ["Sparkie", "Hey Sparkie are you there?", "Sparkie are you there？", "Sparky, summarize this.",
                     "Hi Sparky", "Hi. It's Sparkie.", "Hello, Sparkie!", "Hi, Sparky, what is a WebSocket?",
                     "Sparkie. Sparkie. Sparkie.", "Sparkie. Is a web socket?", "Hi, Sparkie. Try to",
                     "Sparkie, give me an example", "Sparkie，list the conclusions",
                     "Sparkie is our product", "Hi, Sparky is our product",
                     "Sparkie. Sparkie is our product"]:
            self.assertIsNotNone(addressed_request(text), text)

    def test_mentions_names_and_cancellation_are_not_requests(self):
        for text in ["We discussed Sparkie", "Sparkieville", "Sparkie，never mind", "Sparkie, never mind", "Hi, it is Sparkie who built the product.",
                     "It is Sparkie."]:
            self.assertIsNone(addressed_request(text), text)
