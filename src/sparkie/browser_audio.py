"""Browser AEC audio transport. Keys and provider connections stay server-side."""
import asyncio
import base64
import math
import threading
import time
from dataclasses import dataclass, field

from .audio import AudioFrame
from .providers import ProviderError


@dataclass
class BrowserPlayback:
    item_id: str
    generated: int = 0
    played: int = 0
    finished: bool = False
    cancelled: threading.Event = field(default_factory=threading.Event)

    def played_ms(self, now=None):
        return self.played // 48


class BrowserAudio:
    def __init__(self, *, max_seconds, on_event):
        self.max_seconds, self.on_event = max_seconds, on_event
        self.outputs, self.output = {}, None
        self.queue = asyncio.Queue(maxsize=150)
        self.stopped = False
        self.captured_samples = 0
        self.audio_origin = None
        self.timing_reliable = False
        self.echo_mode = 'browser_aec'
        self._gate_until = 0
        self.generation = 0
        self.sequence = 0
        self.last_meter = 0
        self.settings = {}
        self._stats_samples = self._stats_squared = self._stats_clipped = self._stats_zero = 0
        self._stats_peak = 0
        self._last_packet = None
        self._max_packet_gap = 0

    async def join(self):
        self.on_event('audio_open', echo_mode=self.echo_mode, sample_rate=24000)

    def accept(self, command):
        if command['action'] == 'audio_settings':
            self.settings = {k: command.get(k) for k in ('echoCancellation', 'noiseSuppression', 'sampleRate',
                                                       'contextState', 'trackState', 'trackMuted',
                                                       'trackEnabled', 'autoGainControl', 'deviceLabel')}
            self.on_event('browser_audio_settings', **self.settings)
        elif command['action'] == 'audio_input' and not self.stopped:
            pcm = base64.b64decode(command['pcm'], validate=True)
            if not pcm or len(pcm) % 2 or len(pcm) > 4800:
                raise ProviderError('invalid_browser_audio')
            if command.get('sequence') != self.sequence:
                raise ProviderError('browser_audio_sequence_gap')
            self.queue.put_nowait(AudioFrame(self.sequence, pcm, 24000))
            self.sequence += 1
            self.captured_samples += len(pcm) // 2
            now = time.monotonic()
            samples = memoryview(pcm).cast('h')
            peak = max((abs(v) for v in samples), default=0)
            self._stats_samples += len(samples)
            self._stats_squared += sum(v * v for v in samples)
            self._stats_clipped += sum(abs(v) >= 32760 for v in samples)
            self._stats_zero += sum(v == 0 for v in samples)
            self._stats_peak = max(self._stats_peak, peak)
            if self._last_packet is not None:
                self._max_packet_gap = max(self._max_packet_gap, now - self._last_packet)
            self._last_packet = now
            if self._stats_samples >= 48000:
                rms = math.sqrt(self._stats_squared / self._stats_samples) / 32768
                self.on_event('audio_input_diagnostics',
                              captured_seconds=round(self.captured_samples / 24000, 2),
                              rms_dbfs=round(20 * math.log10(max(rms, 1e-6)), 1),
                              peak=round(self._stats_peak / 32768, 4),
                              clipped_fraction=round(self._stats_clipped / self._stats_samples, 4),
                              zero_fraction=round(self._stats_zero / self._stats_samples, 4),
                              max_packet_gap_ms=round(self._max_packet_gap * 1000))
                self._stats_samples = self._stats_squared = self._stats_clipped = self._stats_zero = 0
                self._stats_peak = self._max_packet_gap = 0
            if now - self.last_meter >= .1:
                self.last_meter = now
                self.on_event('audio_level', peak=peak / 32768, gated=False, timing_reliable=False)
        elif command['action'] == 'audio_progress' and command.get('generation') == self.generation:
            output = self.outputs.get(command.get('item_id'))
            if output and not output.cancelled.is_set():
                output.played = min(output.generated, max(output.played, int(command.get('played_bytes', 0))))
                self.output = output

    async def audio(self):
        deadline = time.monotonic() + self.max_seconds if self.max_seconds else float('inf')
        try:
            while not self.stopped and time.monotonic() < deadline:
                try:
                    frame = await asyncio.wait_for(self.queue.get(), .25)
                except TimeoutError:
                    continue
                yield frame
        finally:
            self.request_stop()
            self.on_event('audio_input_ended')

    def append_output(self, item_id, pcm):
        output = self.outputs.setdefault(item_id, BrowserPlayback(item_id))
        self.output = output
        if output.cancelled.is_set():
            return
        output.generated += len(pcm)
        self.on_event('audio_output', item_id=item_id, generation=self.generation,
                      pcm=base64.b64encode(pcm).decode())

    def finish_output(self, item_id):
        if item_id in self.outputs:
            self.outputs[item_id].finished = True

    async def stop_speaking(self):
        for output in self.outputs.values():
            output.cancelled.set()
        self.generation += 1
        self.on_event('audio_clear', generation=self.generation)

    def request_stop(self):
        self.stopped = True

    async def leave(self):
        self.request_stop()
        await self.stop_speaking()

    def diagnostics(self):
        return {'transport': 'browser', 'echo_mode': self.echo_mode, 'settings': self.settings,
                'captured_seconds': self.captured_samples / 24000, 'timing_reliable': False}
