"""Adapt Zoom's paced PCM32k bridge to the existing Realtime PCM24k transport.

A response streams as bounded 100ms packets; it never waits for the whole answer.
Playback accounting is conservative SDK submission progress, not remote DAC time.
"""
import asyncio
from collections import deque
from dataclasses import dataclass, field
import threading
import time

import numpy as np
import soxr

from .audio import AudioFrame
from .providers import ProviderError, PlaybackLimitError, failure_details


class PCMResampler:
    def __init__(self, source, target):
        self.stream = soxr.ResampleStream(source, target, 1, dtype='int16', quality='HQ')

    def feed(self, pcm, *, final=False):
        if len(pcm) % 2:
            raise ProviderError('Invalid PCM16 length')
        samples = np.frombuffer(pcm, dtype='<i2').astype(np.int16, copy=False)
        return self.stream.resample_chunk(samples, last=final).astype('<i2', copy=False).tobytes()


@dataclass
class ZoomPlayback:
    item_id: str
    generated: int = 0  # Original 24kHz bytes.
    submitted: int = 0  # Acknowledged 32kHz bytes, excluding final zero padding.
    finished: bool = False
    drained: bool = False
    cancelled: threading.Event = field(default_factory=threading.Event)
    pending: bytearray = field(default_factory=bytearray)
    resampler: PCMResampler = field(default_factory=lambda: PCMResampler(24000, 32000))

    def played_ms(self, now=None):
        if self.drained:
            return self.generated // 48
        return min(self.generated // 48, self.submitted // 64)


class RealtimeZoomAudio:
    PACKET_BYTES = 6400  # 100ms; native SDK paces its five 20ms frames.
    MAX_BUFFER_SECONDS = 120
    MAX_BUFFER_BYTES = 64000 * MAX_BUFFER_SECONDS  # Bounded backlog, not total reply duration.

    def __init__(self, meeting, *, on_event):
        self.meeting, self.on_event = meeting, on_event
        # Realtime needs one continuous mixed clock, not concatenated participant streams.
        if hasattr(meeting, "participant_audio"):
            meeting.participant_audio = False
        self.outputs, self.output = {}, None
        self.waiting = deque()
        self.changed = asyncio.Event()
        self.worker = self.play_task = None
        self.failure = None
        self.stopped = False
        self.interrupting = False
        self._stop_lock = asyncio.Lock()
        self.captured_samples = 0
        self.audio_origin = None
        self.timing_reliable = False
        # Match the native bridge's existing echo gate; no full-duplex AEC claim.
        self.echo_mode = 'speaker'
        self.coverage_reason = 'zoom_echo_gate'
        self._gate_until = 0
        self.input_resampler = PCMResampler(32000, 24000)
        self.buffered = 0
        self.meeting.on_event = on_event
        self.meeting.input_gate = self.input_gated
        self.meeting.playback_event_interval = 5.0
        self.input_samples = 0
        self.gate_spans = deque()
        self.gated_samples = 0
        self.output_allowed = lambda item_id: True
        self.output_drained = lambda: None

    @property
    def duration_expired(self):
        return getattr(self.meeting, 'duration_expired', False)

    def input_gated(self):
        # Cover generation gaps and stalled SDK calls, not just estimated packet duration.
        return (self.interrupting or self.play_task is not None or
                any(not o.cancelled.is_set() and not o.drained for o in self.outputs.values()) or
                time.monotonic() < self._gate_until)

    def input_frame(self, sequence, pcm):
        start = self.captured_samples
        end = start + len(pcm) // 2
        gated = False
        while self.gate_spans and self.gate_spans[0][1] <= start:
            self.gate_spans.popleft()
        for left, right in self.gate_spans:
            if left >= end:
                break
            if right > start:
                gated = True
                break
        self.captured_samples = end
        if gated:
            self.gated_samples += len(pcm) // 2
        # Conservatively silence an entire chunk overlapping a captured gate interval.
        return AudioFrame(sequence, bytes(len(pcm)) if gated else pcm, 24000, gated=gated)

    async def join(self):
        await self.meeting.join()
        self.worker = asyncio.create_task(self.pump())
        self.on_event('audio_open', transport='zoom', sample_rate=24000,
                      zoom_sample_rate=32000, echo_mode='silence_during_playback_plus_350ms')

    async def audio(self):
        sequence = 0
        async for frame in self.meeting.audio():
            if self.failure:
                raise self.failure
            if frame.sample_rate != 32000:
                raise ProviderError('Zoom bridge requires PCM16 mono 32000Hz')
            gated = frame.gated if frame.gated is not None else self.input_gated()
            start = self.input_samples * 3 // 4
            self.input_samples += len(frame.pcm) // 2
            if gated:
                end = (self.input_samples * 3 + 3) // 4
                if self.gate_spans and self.gate_spans[-1][1] >= start:
                    self.gate_spans[-1] = (self.gate_spans[-1][0], end)
                else:
                    self.gate_spans.append((start, end))
            pcm = self.input_resampler.feed(bytes(len(frame.pcm)) if gated else frame.pcm)
            if pcm:
                yield self.input_frame(sequence, pcm)
                sequence += 1
        if self.failure:
            raise self.failure
        if not self.stopped:
            pcm = self.input_resampler.feed(b'', final=True)
            if pcm:
                yield self.input_frame(sequence, pcm)

    def append_output(self, item_id, pcm):
        if not self.output_allowed(item_id):
            return
        if self.stopped:
            return
        if self.failure:
            raise self.failure
        if not pcm or len(pcm) % 2:
            raise ProviderError('Invalid Realtime PCM')
        output = self.outputs.get(item_id)
        if output is None:
            output = ZoomPlayback(item_id)
            self.outputs[item_id] = output
            self.waiting.append(output)
        if output.cancelled.is_set():
            return
        if output.finished:
            raise ProviderError('Audio arrived after output completion')
        output.generated += len(pcm)
        self.enqueue(output, output.resampler.feed(pcm))

    def enqueue(self, output, pcm):
        if self.buffered + len(pcm) > self.MAX_BUFFER_BYTES:
            raise PlaybackLimitError('Zoom Realtime playback queue full')
        output.pending.extend(pcm)
        self.buffered += len(pcm)
        self.changed.set()

    def finish_output(self, item_id):
        output = self.outputs.get(item_id)
        if output and not output.finished and not output.cancelled.is_set():
            self.enqueue(output, output.resampler.feed(b'', final=True))
            output.finished = True
            self.changed.set()

    async def pump(self):
        try:
            while not self.stopped:
                self.changed.clear()
                if self.interrupting:
                    await self.changed.wait()
                    continue
                if self.output is None or self.output.cancelled.is_set() or self.output.drained:
                    self.output = self.waiting.popleft() if self.waiting else None
                output = self.output
                if output is None:
                    await self.changed.wait()
                    continue
                if output.cancelled.is_set():
                    continue
                if len(output.pending) < self.PACKET_BYTES and not output.finished:
                    await self.changed.wait()
                    continue
                if not output.pending:
                    output.drained = True
                    # Reclaim resampling state; keep tiny progress records for truncation.
                    output.resampler = None
                    self.output_drained()
                    continue
                pcm = bytes(output.pending[:self.PACKET_BYTES])
                del output.pending[:len(pcm)]
                self.buffered -= len(pcm)
                # Native bridge pads its final 20ms frame. Only original samples count.
                self._gate_until = time.monotonic() + len(pcm) / 64000 + .35
                self.play_task = asyncio.create_task(self.meeting.play_audio(pcm, 32000))
                try:
                    await self.play_task
                except asyncio.CancelledError:
                    if not output.cancelled.is_set() or self.stopped:
                        raise
                finally:
                    self.play_task = None
                    self._gate_until = time.monotonic() + .35
                if not output.cancelled.is_set():
                    first = output.submitted == 0
                    output.submitted += len(pcm)
                    if first:
                        self.on_event('zoom_realtime_audio_submitted', item_id=output.item_id,
                                      note='SDK submission progress only; remote audibility is not measured')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.failure = exc
            self.meeting.request_stop()
            self.on_event('audio_failed', **failure_details(exc))

    async def stop_speaking(self):
        async with self._stop_lock:
            await self._stop_speaking()

    async def _stop_speaking(self):
        active = self.play_task is not None or any(
            not o.cancelled.is_set() and not o.drained for o in self.outputs.values())
        if not active:
            return  # Preserve a real existing tail, but never create one for idle speech.
        self.interrupting = True
        for output in self.outputs.values():
            if not output.drained:
                output.cancelled.set()
                output.pending.clear()
                output.resampler = None
        self.buffered = 0
        self.waiting.clear()
        task = self.play_task
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        try:
            await self.meeting.stop_speaking()
        except BaseException as exc:
            self.failure = exc if isinstance(exc, Exception) else ProviderError('zoom_cancel_aborted')
            self.meeting.request_stop()
            raise
        finally:
            self.interrupting = False
            self._gate_until = time.monotonic() + .35
            self.changed.set()

    def request_stop(self):
        self.stopped = True
        self.meeting.request_stop()
        self.changed.set()

    async def leave(self):
        self.request_stop()
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
            self.worker = None
        try:
            await self.stop_speaking()
        finally:
            await self.meeting.leave()

    def diagnostics(self):
        return {**self.meeting.diagnostics(), 'transport': 'zoom-realtime',
                'playback_buffer_limit_bytes': self.MAX_BUFFER_BYTES,
                'response_limit_seconds': None,
                'gated_samples': self.gated_samples,
                'gate_basis': 'bridge_receive_before_queue; native packet gate also active',
                'realtime_sample_rate': 24000, 'playback_packet_ms': 100,
                'progress_basis': 'completed SDK packets; conservative on interruption',
                'remote_audibility_verified': False, 'timing_reliable': False}
