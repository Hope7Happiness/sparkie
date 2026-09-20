"""Direct documented wire APIs; all credentials remain in the Python process."""
import asyncio
import json
from urllib.parse import urlencode

from websockets.asyncio.client import connect

from .contracts import TranscriptEvent, SpeechActivity


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
        'semantic_realtime_error': ('openai', 'semantic_realtime_error'),
        'semantic_realtime_closed': ('openai', 'semantic_realtime_closed'),
        'semantic_configuration_not_applied': ('openai', 'semantic_configuration_not_applied'),
        'semantic_deepgram_error': ('deepgram', 'semantic_deepgram_error'),
        'semantic_deepgram_closed': ('deepgram', 'semantic_deepgram_closed'),
        'semantic_alignment_missing_words': ('deepgram', 'semantic_alignment_missing_words'),
        'semantic_transcript_alignment_timeout': ('session', 'semantic_transcript_alignment_timeout'),
        'semantic_turn_buffer_limit': ('session', 'semantic_turn_buffer_limit'),
        'semantic_provider_close_timeout': ('session', 'semantic_provider_close_timeout'),
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
                raise ProviderError("Transcript segment limit reached; restart the session")
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
    """Streaming Deepgram adapter with an injectable connection for tests."""
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
