"""Local PCM24k streaming playback adapter; no Zoom dependency."""
from collections import deque
import queue
import threading
import time
from dataclasses import dataclass, field

from .local_audio import LocalAudioMeeting
from .providers import ProviderError


@dataclass
class AudioOutput:
    item_id: str
    chunks: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=512))
    pending: bytes = b''
    generated: int = 0
    scheduled: int = 0
    first_dac: float | None = None
    last_dac: float | None = None
    finished: bool = False
    cancelled: threading.Event = field(default_factory=threading.Event)
    # Each block records its scheduled DAC time; underruns do not count as played speech.
    blocks: list = field(default_factory=list)

    def played_ms(self, now=None):
        now = time.monotonic() if now is None else now
        return int(sum(max(0, min(length, (now - start) * 48000)) for start, length in self.blocks) / 48)


class RealtimeLocalAudio(LocalAudioMeeting):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rate = 24000
        self.stream_latency = .06
        self.output = None
        self.outputs = {}
        self.waiting_outputs = deque()

    def append_output(self, item_id, pcm):
        if not pcm or len(pcm) % 2:
            raise ProviderError('Invalid Realtime PCM')
        stream = self.outputs.get(item_id)
        if stream is None:
            stream = AudioOutput(item_id)
            self.outputs[item_id] = stream
            if self.output is None:
                self.output = stream
            else:
                self.waiting_outputs.append(stream)
        if stream.cancelled.is_set():
            return
        stream.generated += len(pcm)
        if stream.generated > 24000 * 2 * 120:
            raise ProviderError('Realtime response exceeds playback limit')
        try:
            stream.chunks.put_nowait(pcm)
        except queue.Full:
            raise ProviderError('Realtime playback queue full') from None

    def finish_output(self, item_id):
        if item_id in self.outputs:
            self.outputs[item_id].finished = True

    async def stop_speaking(self):
        await super().stop_speaking()
        for stream in self.outputs.values():
            stream.cancelled.set()

    def _callback(self, indata, outdata, frames, timing, status):
        stream = self.output
        if stream and (stream.cancelled.is_set() or (stream.finished and not stream.pending and stream.chunks.empty())):
            while self.waiting_outputs:
                stream = self.waiting_outputs.popleft()
                self.output = stream
                if not stream.cancelled.is_set():
                    break
        active = stream and not stream.cancelled.is_set() and (
            stream.pending or not stream.chunks.empty() or not stream.finished)
        if active:
            self._gate_until = time.monotonic() + timing.outputBufferDacTime - timing.currentTime + frames / self.rate + self.echo_tail
        super()._callback(indata, outdata, frames, timing, status)
        if not active:
            return
        offset = 0
        while offset < len(outdata):
            if not stream.pending:
                try:
                    stream.pending = stream.chunks.get_nowait()
                except queue.Empty:
                    break
            length = min(len(outdata) - offset, len(stream.pending))
            outdata[offset:offset + length] = stream.pending[:length]
            stream.pending = stream.pending[length:]
            offset += length
        if offset:
            dac = time.monotonic() + timing.outputBufferDacTime - timing.currentTime
            stream.blocks.append((dac, offset))
            stream.scheduled += offset
            stream.last_dac = dac + offset / 48000
            if stream.first_dac is None:
                stream.first_dac = dac
                self.last_playback_started_at = dac
                if self.on_event:
                    self._loop.call_soon_threadsafe(lambda: self.on_event(
                        'realtime_audio_started', item_id=stream.item_id, dac_time=dac))
