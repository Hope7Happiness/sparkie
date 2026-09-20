"""Per-speaker semantic turn boundaries, aligned to finalized Deepgram words.

Both providers receive the same media timeline. Deepgram endpointing can finalize
words early, but only Realtime semantic VAD can release an assembled human turn.
"""
import asyncio
import base64
from bisect import bisect_right
from collections import deque
from contextlib import aclosing
import json
from urllib.parse import urlencode

from websockets.asyncio.client import connect

from .contracts import SpeechActivity, TranscriptEvent
from .providers import ProviderError, deepgram_connect
from .realtime_zoom_audio import PCMResampler

SEMANTIC_EAGERNESS = 'medium'


def semantic_session_config(model):
    return {'type': 'session.update', 'session': {
        'type': 'realtime', 'model': model, 'output_modalities': ['text'],
        'audio': {'input': {'format': {'type': 'audio/pcm', 'rate': 24000},
                            'turn_detection': {'type': 'semantic_vad', 'eagerness': SEMANTIC_EAGERNESS,
                                               'create_response': False, 'interrupt_response': False}}},
        'tools': []}}


class SemanticTurnBuffer:
    """Provider media milliseconds, never arrival time, define turn membership."""
    def __init__(self, meeting_id):
        self.meeting_id = meeting_id
        self.words = []
        self.seen = set()
        self.ends = []
        self.completed = 0
        self.watermark = 0
        self.active = set()
        self.latest_word = None

    def speech(self, start, end):
        if self.completed and start < self.ends[self.completed - 1]:
            return []
        self.latest_word = max(self.latest_word or (start, end), (start, end))
        turn = bisect_right(self.ends, start)
        if turn in self.active:
            return []
        self.active.add(turn)
        return [SpeechActivity('started', round(start), stream_id=str(turn))]

    def result(self, message):
        if message.get('type') != 'Results':
            return []
        alternatives = message.get('channel', {}).get('alternatives', [])
        alternative = alternatives[0] if alternatives else {}
        text = alternative.get('transcript', '').strip()
        words = alternative.get('words', [])
        events = []
        if text and not words:
            # No guessing which side of a boundary an untimed phrase belongs to.
            raise ProviderError('semantic_alignment_missing_words')
        for word in words:
            start, end = float(word['start']) * 1000, float(word['end']) * 1000
            if self.completed and start < self.ends[self.completed - 1]:
                continue
            value = word.get('punctuated_word') or word.get('word', '')
            key = (start, end, value)
            if key in self.seen:
                continue
            if any(c.isalnum() for c in value):
                events.extend(self.speech(start, end))
            if message.get('is_final'):
                self.seen.add(key)
                self.words.append((start, end, value))
        if message.get('is_final'):
            self.watermark = max(self.watermark,
                                 (message.get('start', 0) + message.get('duration', 0)) * 1000)
        if len(self.seen) > 16000 or len(self.ends) > 4096:
            raise ProviderError('semantic_turn_buffer_limit')
        events.extend(self.flush())
        return events

    def boundary(self, end):
        if self.ends and end <= self.ends[-1]:
            return []
        self.ends.append(end)
        events = []
        # A delayed boundary for the old turn must not mark newer speech quiet.
        if self.latest_word and self.latest_word[0] >= end:
            events.extend(self.speech(*self.latest_word))
        events.extend(self.flush())
        return events

    def flush(self):
        events = []
        while self.completed < len(self.ends) and self.watermark >= self.ends[self.completed]:
            turn = self.completed
            end = self.ends[turn]
            selected = sorted(word for word in self.words if word[0] < end)
            self.words = [word for word in self.words if word[0] >= end]
            self.completed += 1
            text = ' '.join(word[2] for word in selected).strip()
            if text:
                events.append(TranscriptEvent(self.meeting_id, f'semantic-{turn}',
                                              round(max(word[1] for word in selected)), text))
            self.active.discard(turn)
            events.append(SpeechActivity('stopped', round(end), stream_id=str(turn)))
        return events


class SemanticTurnEars:
    """A separate tool-free Realtime detector per non-self participant stream."""
    def __init__(self, deepgram_key, realtime_key, meeting_id, *, model='gpt-realtime-2.1',
                 stt_model='nova-3', language='en-US', connector=connect,
                 dg_connector=deepgram_connect, alignment_timeout=5, on_event=None):
        self.deepgram_key, self.realtime_key, self.meeting_id = deepgram_key, realtime_key, meeting_id
        self.model, self.stt_model, self.language = model, stt_model, language
        self.connector, self.dg_connector = connector, dg_connector
        self.alignment_timeout = alignment_timeout
        self.on_event = on_event or (lambda *a, **k: None)
        self.on_ready = None
        self.speech_events = True

    async def transcribe(self, frames):
        messages = asyncio.Queue(maxsize=256)
        buffer = SemanticTurnBuffer(self.meeting_id)
        ready = asyncio.Event()
        dg_lock = asyncio.Lock()
        rt_lock = asyncio.Lock()
        sent_ms = 0
        finalizations = deque()
        deadlines = {}
        url = 'wss://api.openai.com/v1/realtime?' + urlencode({'model': self.model})
        async with self.dg_connector(self.deepgram_key, 32000, self.stt_model, self.language) as dg, \
                self.connector(url, additional_headers={'Authorization': f'Bearer {self.realtime_key}'},
                               open_timeout=15, close_timeout=3, max_size=2**20) as rt:
            async def send_rt(value):
                async with rt_lock:
                    async with asyncio.timeout(5):
                        await rt.send(json.dumps(value))

            await send_rt(semantic_session_config(self.model))

            async def receive(socket, provider):
                async for raw in socket:
                    await messages.put((provider, json.loads(raw)))
                await messages.put((provider + '_closed', None))

            async def send():
                nonlocal sent_ms
                async with asyncio.timeout(15):
                    await ready.wait()
                if self.on_ready:
                    self.on_ready()
                resampler = PCMResampler(32000, 24000)
                async with aclosing(frames) as stream:
                    async for frame in stream:
                        if frame.sample_rate != 32000 or not frame.pcm or len(frame.pcm) % 2:
                            raise ProviderError('semantic_invalid_pcm')
                        async with dg_lock:
                            async with asyncio.timeout(5):
                                await dg.send(frame.pcm)
                            sent_ms += len(frame.pcm) / 64
                        pcm = resampler.feed(frame.pcm)
                        if pcm:
                            await send_rt({'type': 'input_audio_buffer.append',
                                           'audio': base64.b64encode(pcm).decode()})
                pcm = resampler.feed(b'', final=True)
                if pcm:
                    await send_rt({'type': 'input_audio_buffer.append',
                                   'audio': base64.b64encode(pcm).decode()})
                await messages.put(('input_closed', None))
                async with dg_lock:
                    async with asyncio.timeout(5):
                        await dg.send(json.dumps({'type': 'CloseStream'}))

            async def guarded(coro):
                try:
                    await coro
                except Exception as exc:
                    await messages.put(('failed', exc))

            tasks = [asyncio.create_task(guarded(receive(dg, 'dg'))),
                     asyncio.create_task(guarded(receive(rt, 'rt'))),
                     asyncio.create_task(guarded(send()))]
            input_closed = False
            closing_deadline = None
            last_vad_start = -1
            try:
                while True:
                    try:
                        provider, message = await asyncio.wait_for(messages.get(), .1)
                    except TimeoutError:
                        provider, message = 'tick', None
                    now = asyncio.get_running_loop().time()
                    if any(now > deadline for index, deadline in deadlines.items()
                           if index >= buffer.completed):
                        raise ProviderError('semantic_transcript_alignment_timeout')
                    if closing_deadline and now > closing_deadline:
                        raise ProviderError('semantic_provider_close_timeout')
                    events = []
                    if provider == 'failed':
                        raise message
                    if provider == 'input_closed':
                        input_closed = True
                        closing_deadline = now + self.alignment_timeout
                    elif provider == 'rt_closed':
                        raise ProviderError('semantic_realtime_closed')
                    elif provider == 'dg_closed':
                        if not input_closed:
                            raise ProviderError('semantic_deepgram_closed')
                        # Never invent a semantic endpoint during shutdown.
                        if buffer.words or buffer.completed < len(buffer.ends):
                            self.on_event('semantic_turn_discarded', reason='stream_closed_before_alignment')
                        break
                    elif provider == 'dg':
                        if message.get('type') == 'Error':
                            raise ProviderError('semantic_deepgram_error')
                        if message.get('type') == 'SpeechStarted':
                            start = round(message.get('timestamp', 0) * 1000)
                            if start > last_vad_start:
                                last_vad_start = start
                                events.append(SpeechActivity('candidate', start,
                                                             stream_id=str(bisect_right(buffer.ends, start))))
                        events.extend(buffer.result(message))
                        if message.get('from_finalize') and finalizations:
                            buffer.watermark = max(buffer.watermark, finalizations.popleft())
                            events.extend(buffer.flush())
                    elif provider == 'rt':
                        kind = message.get('type')
                        if kind == 'error':
                            raise ProviderError('semantic_realtime_error')
                        if kind == 'session.updated':
                            detection = message.get('session', {}).get('audio', {}).get('input', {}).get('turn_detection', {})
                            if (detection.get('type') != 'semantic_vad' or detection.get('eagerness') != SEMANTIC_EAGERNESS or
                                    detection.get('create_response') is not False or
                                    detection.get('interrupt_response') is not False):
                                raise ProviderError('semantic_configuration_not_applied')
                            ready.set()
                            self.on_event('semantic_turn_ready', model=self.model, eagerness=SEMANTIC_EAGERNESS)
                        elif kind == 'input_audio_buffer.speech_stopped':
                            end = message['audio_end_ms']
                            before = len(buffer.ends)
                            events.extend(buffer.boundary(end))
                            if len(buffer.ends) > before:
                                self.on_event('semantic_turn_boundary', audio_end_ms=end)
                                deadlines[before] = now + self.alignment_timeout
                                if buffer.completed <= before and not input_closed:
                                    async with dg_lock:
                                        finalizations.append(sent_ms)
                                        async with asyncio.timeout(5):
                                            await dg.send(json.dumps({'type': 'Finalize'}))
                        elif kind == 'input_audio_buffer.committed':
                            # Detector sessions never answer or retain meeting history.
                            await send_rt({'type': 'conversation.item.delete', 'item_id': message['item_id']})
                    for event in events:
                        yield event
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
