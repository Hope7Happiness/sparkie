import asyncio
import json
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import httpx
from sparkie.audio import AudioFrame
from sparkie.providers import DeepgramEars, DeepgramMouth, ElevenLabs, OpenAIBrain, ProviderError, Utterances, deepgram_url


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
        self.assertEqual(parser.feed(message("你在吗", start=1)), "Sparkie 你在吗")
        self.assertIsNone(parser.feed(message("你在吗", start=1)))

    def test_streaming_error_is_not_a_transcript(self):
        with self.assertRaises(ProviderError):
            Utterances().feed({"type": "Error"})

    def test_pcm_and_language_explicit_in_url(self):
        url = deepgram_url(32000, "nova-3", "zh-CN")
        for parameter in ["encoding=linear16", "channels=1", "sample_rate=32000", "language=zh-CN"]:
            self.assertIn(parameter, url)


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_deepgram_tts_headerless_pcm_request(self):
        def handle(request):
            self.assertEqual(request.url.path, "/v1/speak")
            self.assertEqual(request.headers["Authorization"], "Token test-key")
            self.assertEqual(request.url.params["encoding"], "linear16")
            self.assertEqual(request.url.params["container"], "none")
            self.assertEqual(request.url.params["sample_rate"], "32000")
            self.assertEqual(json.loads(request.content), {"text": "I'm here."})
            return httpx.Response(200, content=b"\0\0" * 320, headers={"content-type": "audio/linear16"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            audio = await DeepgramMouth("test-key", client=client).synthesize("I'm here.")
            self.assertEqual(len(audio), 640)

    async def test_deepgram_tts_rejects_wrong_format_and_redacts_error_body(self):
        for response in [httpx.Response(200, content=b'RIFF0000', headers={"content-type":"audio/linear16"}),
                         httpx.Response(200, json={"error":"bad"}),
                         httpx.Response(429, text="secret-body")]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _, r=response: r)) as client:
                with self.assertRaises(ProviderError) as error:
                    await DeepgramMouth("test-key", client=client).synthesize("hi")
                self.assertNotIn("secret-body", str(error.exception))

    async def test_english_voice_rejects_chinese_before_network_call(self):
        with self.assertRaisesRegex(ValueError, "Chinese"):
            await DeepgramMouth("unused-key").synthesize("我在。")

    async def test_elevenlabs_request_and_pcm_output(self):
        def handle(request):
            self.assertEqual(request.headers["xi-api-key"], "test-key")
            self.assertEqual(request.url.params["output_format"], "pcm_32000")
            self.assertEqual(json.loads(request.content)["text"], "我在。")
            return httpx.Response(200, content=b"\0\0" * 320)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            audio = await ElevenLabs("test-key", "test-voice", "eleven_flash_v2_5", client).synthesize("我在。")
        self.assertEqual(len(audio), 640)

    async def test_failure_does_not_expose_provider_body(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(401, text="sensitive-body"))) as client:
            with self.assertRaises(ProviderError) as error:
                await ElevenLabs("secret", "voice", "model", client).synthesize("hi")
            self.assertIn("401", str(error.exception))
            self.assertNotIn("sensitive-body", str(error.exception))

    async def test_openai_wire_request_and_answer(self):
        def handle(request):
            body = json.loads(request.content)
            self.assertFalse(body["store"])
            self.assertIn("此前的决策", body["input"])
            return httpx.Response(200, json={"output": [{"type": "message", "content": [{"type": "output_text", "text": "先演示入会。"}]}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            answer = await OpenAIBrain("test-key", "test-model", client).answer(["此前的决策", "Sparkie，总结一下"])
            self.assertEqual(answer, "先演示入会。")

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
                    await self.queue.put(json.dumps(message("Sparkie，你在吗？")))
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
        self.assertEqual(events[0].text, "Sparkie，你在吗？")
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
