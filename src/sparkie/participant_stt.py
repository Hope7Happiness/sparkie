"""Bounded per-participant streaming STT; provider connections are supplied by a factory."""
import asyncio
from contextlib import aclosing
from dataclasses import replace

from .audio import AudioFrame
from .contracts import SpeechActivity
from .providers import ProviderError


class ParticipantEars:
    def __init__(self, factory, *, speaker_name=lambda ident: ident, is_self=lambda ident: False,
                 idle_seconds=1.5, max_streams=32, queue_frames=500, on_event=None, speech_events=False):
        if not 1 <= max_streams <= 64 or idle_seconds <= 0:
            raise ValueError('Invalid participant STT limits')
        self.factory, self.speaker_name, self.is_self = factory, speaker_name, is_self
        self.idle_seconds, self.max_streams, self.queue_frames = idle_seconds, max_streams, queue_frames
        self.on_event = on_event or (lambda *a, **kw: None)
        self.on_ready = None
        self.speech_events = speech_events

    async def transcribe(self, frames):
        output = asyncio.Queue(maxsize=256)
        active, runners = {}, set()
        serial = 0

        async def audio(state):
            cursor = 0
            try:
                while True:
                    try:
                        frame = await asyncio.wait_for(state['queue'].get(), self.idle_seconds)
                    except TimeoutError:
                        return
                    if frame is None:
                        return
                    target = (frame.timestamp_ms - state['origin']) * 32
                    # Preserve quiet gaps within a turn on the common capture clock.
                    gap = max(0, target - cursor)
                    if gap:
                        yield AudioFrame(0, b'\0\0' * gap)
                        cursor += gap
                    yield frame
                    cursor += len(frame.pcm) // 2
            finally:
                state['accepting'] = False

        async def padded_audio(state):
            async with aclosing(audio(state)) as stream:
                async for frame in stream:
                    yield frame
            # Endpoint the last words even when Zoom stops issuing this user's callbacks.
            yield AudioFrame(0, b'\0\0' * 16000)

        async def recognize(ident, state):
            speaking = False
            stream_id = f"{ident}:{state['serial']}"
            try:
                ears = self.factory()
                ears.speech_events = self.speech_events
                ears.on_ready = lambda: self.on_event('participant_stt_ready', speaker_id=ident)
                async with aclosing(ears.transcribe(padded_audio(state))) as stream:
                    async for event in stream:
                        if isinstance(event, SpeechActivity):
                            speaking = event.phase == 'started'
                            await output.put(replace(event, speaker_id=ident, stream_id=stream_id,
                                                     timestamp_ms=state['origin'] + event.timestamp_ms))
                            continue
                        await output.put(replace(event, speaker_id=ident,
                            speaker=self.speaker_name(ident),
                            timestamp_ms=state['origin'] + event.timestamp_ms,
                            event_id=f"{ident}:{state['serial']}:{event.event_id}"))
                if speaking:
                    await output.put(SpeechActivity('stopped', round(state['last_ms']), ident, stream_id))
            except Exception as exc:
                await output.put(exc)
            finally:
                state['accepting'] = False
                if active.get(ident) is state:
                    del active[ident]
                self.on_event('participant_stt_closed', speaker_id=ident)

        async def route():
            nonlocal serial
            try:
                if self.on_ready:
                    self.on_ready()  # Router ready; per-user provider readiness is a separate event.
                async for frame in frames:
                    ident = frame.speaker_id
                    if (not ident or frame.timestamp_ms is None or frame.timestamp_ms < 0
                            or frame.sample_rate != 32000 or not frame.pcm or len(frame.pcm) % 2):
                        raise ProviderError('Invalid participant PCM metadata')
                    if self.is_self(ident) or not any(frame.pcm):
                        continue
                    state = active.get(ident)
                    if state and state['accepting'] and frame.timestamp_ms - state['last_ms'] > self.idle_seconds * 1000:
                        state['accepting'] = False
                        state['queue'].put_nowait(None)
                    if state is None or not state['accepting']:
                        if len(runners) >= self.max_streams:
                            raise ProviderError('Participant STT concurrency limit reached')
                        serial += 1
                        state = dict(queue=asyncio.Queue(maxsize=self.queue_frames), accepting=True,
                                     origin=frame.timestamp_ms, last_ms=frame.timestamp_ms, serial=serial)
                        active[ident] = state
                        task = asyncio.create_task(recognize(ident, state))
                        runners.add(task)
                        task.add_done_callback(runners.discard)
                    state['last_ms'] = frame.timestamp_ms + len(frame.pcm) / 64
                    state['queue'].put_nowait(frame)
                    # A buffered source must not starve the independent STT consumers.
                    await asyncio.sleep(0)
                for state in list(active.values()):
                    if state['accepting']:
                        state['accepting'] = False
                        await state['queue'].put(None)
                await asyncio.gather(*list(runners))
                await output.put(None)
            except Exception as exc:
                await output.put(exc)

        pump = asyncio.create_task(route())
        try:
            while True:
                event = await output.get()
                if event is None:
                    return
                if isinstance(event, Exception):
                    raise event
                yield event
        finally:
            pump.cancel()
            tasks = list(runners)
            for task in tasks:
                task.cancel()
            await asyncio.gather(pump, *tasks, return_exceptions=True)
