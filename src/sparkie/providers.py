"""Direct documented wire APIs; all credentials remain in the Python process."""
import asyncio
import json
from urllib.parse import urlencode, quote

import httpx
from websockets.asyncio.client import connect

from .contracts import TranscriptEvent, SpeechActivity
from .reasoning import ANSWER_INSTRUCTIONS, conversation_input


class ProviderError(RuntimeError):
    def __init__(self, message, *, provider_code=None):
        super().__init__(message)
        self.provider_code = provider_code

    def diagnostic_fields(self):
        return {}


class PlaybackLimitError(ProviderError):
    """Bounded playback capacity exhausted; cancel the reply, not the session."""


def failure_details(exc):
    """Only locally defined reasons and code locations; never exception bodies."""
    reasons = {
        'Zoom Realtime playback queue full': ('zoom', 'playback_queue_full'),
        'Realtime response exceeds playback limit': ('audio', 'response_duration_limit'),
        'Invalid Realtime PCM': ('audio', 'invalid_pcm'),
        'Invalid PCM16 length': ('audio', 'invalid_pcm_length'),
        'Audio arrived after output completion': ('zoom', 'audio_after_completion'),
        'Zoom bridge requires PCM16 mono 32000Hz': ('zoom', 'invalid_input_format'),
        'realtime_disconnected': ('openai', 'realtime_disconnected'),
        'realtime_error': ('openai', 'realtime_error'),
        'realtime_response_failed': ('openai', 'realtime_response_failed'),
        'audio_backpressure': ('openai', 'input_queue_full'),
        'provider_startup_timeout': ('session', 'provider_startup_timeout'),
        'provider_closed_before_ready': ('openai', 'closed_before_ready'),
        'provider_closed_during_audio_join': ('openai', 'closed_during_audio_join'),
        'provider_closed_early': ('openai', 'closed_early'),
        'Zoom cancellation acknowledgement timed out': ('zoom', 'cancel_ack_timeout'),
        'Zoom cancellation aborted': ('zoom', 'cancel_aborted'),
        'Zoom bridge requires cancel-v1; rebuild the native receiver': ('zoom', 'bridge_rebuild_required'),
    }
    provider, reason = reasons.get(str(exc), ('unknown', 'unclassified'))
    result = {'error_type': type(exc).__name__, 'provider': provider, 'reason': reason}
    code = getattr(exc, 'provider_code', None)
    if code in ('server_error', 'rate_limit_exceeded', 'insufficient_quota',
                'invalid_api_key', 'invalid_request_error', 'model_not_found',
                'context_length_exceeded', 'session_expired', 'unknown_provider_error'):
        result['provider_code'] = code
    tb = exc.__traceback__
    while tb:
        module = tb.tb_frame.f_globals.get('__name__', '')
        if module.startswith('sparkie.'):
            result['source'] = f'{module}:{tb.tb_frame.f_code.co_name}:{tb.tb_lineno}'
            if provider == 'unknown':
                result['provider'] = {
                    'sparkie.realtime': 'openai',
                    'sparkie.zoom_audio': 'zoom',
                    'sparkie.realtime_zoom_audio': 'zoom',
                }.get(module, 'unknown')
        tb = tb.tb_next
    if isinstance(exc, ProviderError):
        result.update(exc.diagnostic_fields())
    return result


class DeepgramMouth:
    """Aura REST TTS returning headerless PCM16 mono at the engine's 32 kHz."""
    def __init__(self, key: str, model="aura-2-thalia-en", client=None):
        self.key, self.model, self.client = key, model, client

    async def synthesize(self, text: str) -> bytes:
        if not text.strip():
            raise ValueError("TTS text must not be empty")
        if not self.model.startswith("aura-"):
            raise ValueError("This adapter uses /v1/speak and requires an Aura model")
        if self.model.endswith("-en") and any("\u4e00" <= char <= "\u9fff" for char in text):
            raise ValueError("The configured English Deepgram voice does not support Chinese TTS; use English reply text")

        async def request(client):
            try:
                response = await client.post(
                    "https://api.deepgram.com/v1/speak",
                    params={"model": self.model, "encoding": "linear16", "container": "none", "sample_rate": 32000},
                    headers={"Authorization": f"Token {self.key}"}, json={"text": text},
                )
            except httpx.RequestError:
                raise ProviderError("Deepgram TTS network request failed") from None
            if response.status_code != 200:
                raise ProviderError(f"Deepgram TTS HTTP {response.status_code}; check API key, TTS permission, model and quota")
            audio = response.content
            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            if content_type not in {"audio/linear16", "audio/l16", "application/octet-stream"}:
                raise ProviderError("Deepgram TTS returned an unexpected content type")
            if not audio or len(audio) % 2 or len(audio) > 32000 * 2 * 30 or audio[:4] == b"RIFF":
                raise ProviderError("Deepgram TTS returned invalid, containerized or >30s PCM audio")
            return audio

        if self.client:
            return await request(self.client)
        async with httpx.AsyncClient(timeout=30) as client:
            return await request(client)


class ElevenLabs:
    def __init__(self, key: str, voice: str, model: str, client=None):
        self.key, self.voice, self.model = key, voice, model
        self.client = client

    async def synthesize(self, text: str) -> bytes:
        async def request(client):
            response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{quote(self.voice, safe='')}",
                params={"output_format": "pcm_32000"},
                headers={"xi-api-key": self.key},
                json={"text": text, "model_id": self.model},
            )
            if response.status_code != 200:
                raise ProviderError(f"ElevenLabs HTTP {response.status_code}; check key, TTS permission, voice access and quota")
            audio = response.content
            if not audio or len(audio) % 2 or len(audio) > 32000 * 2 * 30:
                raise ProviderError("ElevenLabs returned invalid or >30s PCM audio")
            return audio
        if self.client:
            return await request(self.client)
        async with httpx.AsyncClient(timeout=30) as client:
            return await request(client)


class OpenAIBrain:
    def __init__(self, key: str, model: str, client=None):
        self.key, self.model, self.client = key, model, client

    async def answer(self, transcript: list[str]) -> str:
        async def request(client):
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {self.key}"},
                json={"model": self.model, "store": False,
                      "instructions": ANSWER_INSTRUCTIONS,
                      "input": conversation_input(transcript), "max_output_tokens": 200},
            )
            if response.status_code != 200:
                raise ProviderError(f"OpenAI HTTP {response.status_code}; check API key, project quota and model access")
            result = "".join(part.get("text", "") for item in response.json().get("output", [])
                             if item.get("type") == "message" for part in item.get("content", [])
                             if part.get("type") == "output_text").strip()
            if not result:
                raise ProviderError("OpenAI returned no answer text")
            return result[:400]
        if self.client:
            return await request(self.client)
        async with httpx.AsyncClient(timeout=30) as client:
            return await request(client)


def deepgram_url(rate: int, model: str, language: str) -> str:
    return "wss://api.deepgram.com/v1/listen?" + urlencode({
        "model": model, "language": language, "encoding": "linear16",
        "sample_rate": rate, "channels": 1, "interim_results": "true",
        "vad_events": "true", "endpointing": 300, "utterance_end_ms": 1000, "punctuate": "true", "keyterm": "Sparkie",
    })


def deepgram_connect(key: str, rate: int, model: str, language: str):
    return connect(deepgram_url(rate, model, language),
                   additional_headers={"Authorization": f"Token {key}"},
                   open_timeout=15, close_timeout=3, max_size=2**20)


class Utterances:
    """Accumulate final segments until speech_final; ignore repeated and interim results."""
    def __init__(self):
        self.parts = []
        self.seen = set()
        self.end_seconds = 0.0
        self._pending_end = 0.0

    def flush(self):
        if not self.parts:
            return None
        result = " ".join(self.parts)
        self.parts.clear()
        self.end_seconds = self._pending_end
        self._pending_end = 0.0
        return result

    def feed(self, message: dict) -> str | None:
        if message.get("type") == "Error":
            raise ProviderError("Deepgram reported a streaming error")
        if message.get("type") == "UtteranceEnd":
            return self.flush()
        if message.get("type") != "Results" or not message.get("is_final"):
            return None
        alternatives = message.get("channel", {}).get("alternatives", [])
        text = alternatives[0].get("transcript", "").strip() if alternatives else ""
        key = (message.get("start"), message.get("duration"), text)
        if text and key not in self.seen:
            self.seen.add(key)
            if len(self.seen) > 4096:
                raise ProviderError("Transcript segment limit reached; restart primitive")
            self.parts.append(text)
            words = alternatives[0].get("words", [])
            # Last spoken word, not the result span which can include trailing silence.
            end = words[-1].get("end") if words else None
            if end is None:
                end = message.get("start", 0) + message.get("duration", 0)
            self._pending_end = max(self._pending_end, end)
        if sum(map(len, self.parts)) > 16000:
            raise ProviderError("Deepgram did not end the utterance; check endpointing")
        if message.get("speech_final") or message.get("from_finalize"):
            return self.flush()
        return None


class DeepgramEars:
    """Streaming adapter for a future real AudioMeeting. No network in simulation."""
    def __init__(self, key, meeting_id, rate=32000, model="nova-3", language="en-US", connector=deepgram_connect, on_ready=None, on_partial=None, speech_events=False):
        self.key, self.meeting_id, self.rate = key, meeting_id, rate
        self.model, self.language, self.connector = model, language, connector
        self.on_ready = on_ready
        self.on_partial = on_partial
        self.speech_events = speech_events

    async def transcribe(self, frames):
        queue = asyncio.Queue(maxsize=128)
        utterances = Utterances()

        async with self.connector(self.key, self.rate, self.model, self.language) as ws:
            if self.on_ready:
                self.on_ready()
            last_sent = asyncio.get_running_loop().time()
            send_lock = asyncio.Lock()

            async def send():
                nonlocal last_sent
                count = 0
                async for frame in frames:
                    if frame.sample_rate != self.rate or not frame.pcm or len(frame.pcm) % 2:
                        raise ProviderError("Audio must be nonempty PCM16 mono at the configured sample rate")
                    async with send_lock:
                        await ws.send(frame.pcm)
                        last_sent = asyncio.get_running_loop().time()
                    count += 1
                    # Buffered input and websocket sends may both complete inline.
                    if count % 32 == 0:
                        await asyncio.sleep(0)
                async with send_lock:
                    await ws.send(json.dumps({"type": "CloseStream"}))

            async def keepalive():
                while True:
                    await asyncio.sleep(3)
                    async with send_lock:
                        if asyncio.get_running_loop().time() - last_sent >= 3:
                            await ws.send(json.dumps({"type": "KeepAlive"}))

            async def receive():
                sequence = 0
                previous_partial = ''
                speaking = False
                candidate = False
                last_vad_start = -1
                async for raw in ws:
                    message = json.loads(raw)
                    channel = message.get('channel', {})
                    alternatives = channel.get('alternatives', []) if isinstance(channel, dict) else []
                    words = alternatives[0].get('transcript', '').strip() if alternatives else ''
                    key = (message.get('start'), message.get('duration'), words)
                    # A late interim replay of a finalized segment must not
                    # interrupt the answer to that same segment either.
                    replayed_final = key in utterances.seen
                    vad_start = message.get('type') == 'SpeechStarted'
                    timestamp = message.get('timestamp', 0)
                    if vad_start:
                        vad_start = timestamp > last_vad_start
                        last_vad_start = max(last_vad_start, timestamp)
                    has_words = any(c.isalnum() for c in words) and not replayed_final
                    if self.speech_events and not candidate and not speaking and vad_start:
                        candidate = True
                        queue.put_nowait(SpeechActivity('candidate', round(timestamp * 1000)))
                    if self.speech_events and not speaking and has_words:
                        speaking = True
                        timestamp = message.get('timestamp', message.get('start', 0))
                        queue.put_nowait(SpeechActivity('started', round(timestamp * 1000)))
                    text = utterances.feed(message)
                    if self.on_partial and message.get('type') in ('Results', 'UtteranceEnd'):
                        parts = list(utterances.parts)
                        if message.get('type') == 'Results' and not message.get('is_final'):
                            alternatives = message.get('channel', {}).get('alternatives', [])
                            interim = alternatives[0].get('transcript', '').strip() if alternatives else ''
                            if interim:
                                parts.append(interim)
                        partial = ' '.join(parts)
                        if partial != previous_partial:
                            self.on_partial(partial)
                            previous_partial = partial
                    if text:
                        sequence += 1
                        timestamp_ms = round(utterances.end_seconds * 1000)
                        queue.put_nowait(TranscriptEvent(self.meeting_id, f"dg-{sequence}", timestamp_ms, text))
                    if self.speech_events and (speaking or candidate) and not replayed_final and (text or message.get('speech_final') or
                            message.get('type') == 'UtteranceEnd'):
                        speaking = False
                        candidate = False
                        queue.put_nowait(SpeechActivity('stopped', round(utterances.end_seconds * 1000)))

            async def supervise():
                tx = asyncio.create_task(send())
                rx = asyncio.create_task(receive())
                heartbeat = asyncio.create_task(keepalive())
                try:
                    done, _ = await asyncio.wait({tx, rx, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                    if tx in done:
                        heartbeat.cancel()
                        await asyncio.gather(heartbeat, return_exceptions=True)
                        await asyncio.wait_for(rx, timeout=10)
                    elif not tx.done():
                        raise ProviderError("Deepgram closed before the audio source ended")
                    await queue.put(None)
                except Exception as exc:
                    await queue.put(exc)
                finally:
                    for task in (tx, rx, heartbeat):
                        task.cancel()
                    await asyncio.gather(tx, rx, heartbeat, return_exceptions=True)

            runner = asyncio.create_task(supervise())
            try:
                while True:
                    item = await queue.get()
                    if item is None:
                        return
                    if isinstance(item, Exception):
                        raise item
                    yield item
            finally:
                runner.cancel()
                await asyncio.gather(runner, return_exceptions=True)
