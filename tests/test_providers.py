import asyncio
import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sparkie.audio import AudioFrame
from sparkie.contracts import SpeechActivity, TranscriptEvent
from sparkie.providers import DeepgramEars, ProviderError, Utterances, deepgram_url


def message(text, start=0, final=True, end=True):
    return {"type": "Results", "start": start, "duration": 1, "is_final": final,
            "speech_final": end, "channel": {"alternatives": [{"transcript": text}]}}


class UtteranceTests(unittest.TestCase):
    def test_latency_uses_last_word_end_not_trailing_silence(self):
        parser = Utterances()
        result = message("Sparkie", start=0)
        result["duration"] = 2
        result["channel"]["alternatives"][0]["words"] = [{"word": "Sparkie", "end": .6}]
        self.assertEqual(parser.feed(result), "Sparkie")
        self.assertEqual(parser.end_seconds, .6)

    def test_utterance_end_flushes_once_without_speech_final(self):
        parser = Utterances()
        self.assertIsNone(parser.feed(message("Sparkie", end=False)))
        self.assertEqual(parser.feed({"type": "UtteranceEnd"}), "Sparkie")
        self.assertIsNone(parser.feed({"type": "UtteranceEnd"}))

    def test_accumulate_final_segments_and_ignore_duplicates(self):
        parser = Utterances()
        self.assertIsNone(parser.feed(message("wrong partial", final=False)))
        self.assertIsNone(parser.feed(message("Sparkie", end=False)))
        self.assertIsNone(parser.feed(message("Sparkie", end=False)))
        self.assertEqual(parser.feed(message("are you there", start=1)), "Sparkie are you there")
        self.assertIsNone(parser.feed(message("are you there", start=1)))

    def test_streaming_error_is_not_a_transcript(self):
        with self.assertRaises(ProviderError):
            Utterances().feed({"type": "Error"})

    def test_pcm_and_language_explicit_in_url(self):
        url = deepgram_url(32000, "nova-3", "zh-CN")
        for parameter in ["encoding=linear16", "channels=1", "sample_rate=32000", "language=zh-CN"]:
            self.assertIn(parameter, url)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_partial_is_revised_without_becoming_a_final_transcript(self):
        class Socket:
            def __init__(self): self.queue = asyncio.Queue()
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def send(self, payload):
                if isinstance(payload, bytes):
                    for event in [message('wrong word', final=False, end=False),
                                  message('Hello', end=False),
                                  message('world', start=1, final=False, end=False),
                                  message('world', start=1)]:
                        await self.queue.put(json.dumps(event))
                else:
                    await self.queue.put(None)
            def __aiter__(self): return self
            async def __anext__(self):
                event = await self.queue.get()
                if event is None: raise StopAsyncIteration
                return event
        async def frames(): yield AudioFrame(0, bytes(960))
        socket = Socket(); partials = []
        ears = DeepgramEars('test', 'meeting', connector=lambda *args: socket, on_partial=partials.append)
        final = [event.text async for event in ears.transcribe(frames())]
        self.assertEqual(partials, ['wrong word', 'Hello', 'Hello world', ''])
        self.assertEqual(final, ['Hello world'])

    async def test_vad_boundaries_precede_final_text_and_ignore_replayed_finals(self):
        class Socket:
            def __init__(self): self.queue = asyncio.Queue()
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def send(self, payload):
                if isinstance(payload, bytes):
                    events = [{'type': 'SpeechStarted', 'timestamp': 0, 'channel': [0]},
                              message('Sparkie, hello'), message('Sparkie, hello'),
                              message('Sparkie, hello', final=False, end=False),
                              {'type': 'SpeechStarted', 'timestamp': 0, 'channel': [0]},
                              {'type': 'SpeechStarted', 'timestamp': 2, 'channel': [0]},
                              {'type': 'UtteranceEnd', 'channel': [0, 1]}]
                    for event in events: await self.queue.put(json.dumps(event))
                else: await self.queue.put(None)
            def __aiter__(self): return self
            async def __anext__(self):
                event = await self.queue.get()
                if event is None: raise StopAsyncIteration
                return event
        async def frames(): yield AudioFrame(0, bytes(1280))
        socket = Socket()
        ears = DeepgramEars('unused', 'm', connector=lambda *args: socket, speech_events=True)
        events = [e async for e in ears.transcribe(frames())]
        self.assertEqual([e.phase if isinstance(e, SpeechActivity) else e.text for e in events],
                         ['candidate', 'started', 'Sparkie, hello', 'stopped', 'candidate', 'stopped'])
        self.assertIsInstance(events[2], TranscriptEvent)
        self.assertIn('vad_events=true', deepgram_url(32000, 'nova-3', 'en'))

    async def test_deepgram_sends_pcm_and_closes_without_blocking_receiver(self):
        class Socket:
            def __init__(self):
                self.sent = []
                self.queue = asyncio.Queue()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def send(self, payload):
                self.sent.append(payload)
                if isinstance(payload, bytes):
                    await self.queue.put(json.dumps(message("Sparkie， are you there？")))
                elif json.loads(payload)["type"] == "CloseStream":
                    await self.queue.put(None)
            def __aiter__(self):
                return self
            async def __anext__(self):
                result = await self.queue.get()
                if result is None:
                    raise StopAsyncIteration
                return result
        async def frames():
            yield AudioFrame(0, b"\0\0" * 640)
        socket = Socket()
        ears = DeepgramEars("test", "meeting", connector=lambda *args: socket)
        events = [event async for event in ears.transcribe(frames())]
        self.assertEqual(events[0].text, "Sparkie， are you there？")
        self.assertIsInstance(socket.sent[0], bytes)
        self.assertEqual(json.loads(socket.sent[-1])["type"], "CloseStream")

    async def test_idle_keepalive_does_not_cancel_audio_source(self):
        class Socket:
            def __init__(self):
                self.sent = []
                self.keepalive = asyncio.Event()
                self.closed = asyncio.Event()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def send(self, payload):
                self.sent.append(payload)
                if isinstance(payload, str):
                    if json.loads(payload)['type'] == 'KeepAlive':
                        self.keepalive.set()
                    else:
                        self.closed.set()
            def __aiter__(self):
                return self
            async def __anext__(self):
                await self.closed.wait()
                raise StopAsyncIteration
        socket = Socket()
        source_closed = []
        async def frames():
            try:
                await socket.keepalive.wait()
                yield AudioFrame(1, b'\0\0')
            finally:
                source_closed.append(True)
        ears = DeepgramEars('test', 'idle', connector=lambda *args: socket)
        async with asyncio.timeout(6):
            self.assertEqual([event async for event in ears.transcribe(frames())], [])
        self.assertEqual([json.loads(p)['type'] if isinstance(p, str) else 'PCM' for p in socket.sent],
                         ['KeepAlive', 'PCM', 'CloseStream'])
        self.assertEqual(source_closed, [True])
