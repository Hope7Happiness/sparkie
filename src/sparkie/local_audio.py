"""Full-duplex device transport with a conservative speaker-mode input gate."""
import asyncio
import queue
import sys
import threading
import time
from dataclasses import dataclass, field

from .audio import AudioFrame
from .providers import ProviderError


@dataclass
class Playback:
    pcm: bytes
    done: asyncio.Event
    offset: int = 0
    started_at: float | None = None
    ends_at: float | None = None
    cancelled: threading.Event = field(default_factory=threading.Event)


class LocalAudioMeeting:
    """One PCM16 mono 32kHz stream. No raw microphone recordings are persisted."""
    def __init__(self, input_device=None, output_device=None, *, echo_mode="speaker", echo_tail_ms=350,
                 max_seconds=60, driver=None, on_event=None):
        if echo_mode not in {"speaker", "headphones"}:
            raise ValueError("echo_mode must be speaker or headphones")
        if not 0 <= echo_tail_ms <= 2000 or not 0 < max_seconds <= 3600:
            raise ValueError("echo tail must be 0–2000ms; session duration must be 1–3600s")
        self.input_device, self.output_device = input_device, output_device
        self.echo_mode, self.echo_tail = echo_mode, echo_tail_ms / 1000
        self.max_seconds, self.driver, self.on_event = max_seconds, driver, on_event
        self.rate = 32000
        self._queue = queue.Queue(maxsize=100)  # Bounded native audio blocks.
        self._stop = threading.Event()
        self._playback = None
        self._gate_until = 0.0
        self._error = None
        self._stream = None
        self._loop = None
        self.audio_origin = None
        self.last_playback_started_at = None
        self._sequence = 0
        self.captured_samples = 0
        self.gated_samples = 0
        self.input_overflows = 0
        self._overflow_streak = 0
        self.output_underflows = 0
        self.input_peak = 0
        self.current_peak = 0
        self._last_level_at = 0.0
        self._last_capture_at = None
        self._reported_overflows = 0
        self._reported_underflows = 0
        self.callback_count = 0
        self.last_block_frames = 0
        self.max_callback_gap_ms = 0

    def _callback(self, indata, outdata, frames, timing, status):
        now = time.monotonic()
        if self._last_capture_at is not None:
            self.max_callback_gap_ms = max(self.max_callback_gap_ms, round((now - self._last_capture_at) * 1000))
        self._last_capture_at = now
        self.callback_count += 1
        self.last_block_frames = frames
        outdata[:] = b"\0" * len(outdata)
        adc = now + timing.inputBufferAdcTime - timing.currentTime
        dac = now + timing.outputBufferDacTime - timing.currentTime
        if self.audio_origin is None:
            self.audio_origin = adc
        if status.input_overflow:
            self.input_overflows += 1
            self._overflow_streak += 1
            if self._overflow_streak >= 5:
                self._error = "Repeated microphone overflow: samples were lost; restart the session"
        else:
            self._overflow_streak = 0
        if status.output_underflow:
            self.output_underflows += 1

        playback = self._playback
        if playback is not None:
            if playback.cancelled.is_set():
                self._playback = None
                self._gate_until = max(self._gate_until, dac + self.echo_tail)
                self._loop.call_soon_threadsafe(playback.done.set)
            else:
                length = min(len(outdata), len(playback.pcm) - playback.offset)
                outdata[:length] = playback.pcm[playback.offset:playback.offset + length]
                if playback.started_at is None:
                    playback.started_at = dac
                    self.last_playback_started_at = dac
                playback.offset += length
                self._gate_until = dac + length / (self.rate * 2) + self.echo_tail
                if playback.offset == len(playback.pcm):
                    playback.ends_at = dac + length / (self.rate * 2)
                    self._playback = None
                    self._loop.call_soon_threadsafe(playback.done.set)

        if self._stop.is_set():
            return
        pcm = bytes(indata)
        self.captured_samples += frames
        if self.echo_mode == "speaker" and (self._playback is not None or adc < self._gate_until):
            pcm = b"\0" * len(pcm)
            self.gated_samples += frames
        try:
            self._queue.put_nowait(AudioFrame(self._sequence, pcm, self.rate))
            self._sequence += 1
        except queue.Full:
            self._error = "Audio queue full: transcription cannot keep up; restart the session"

    async def join(self):
        if sys.byteorder != "little":
            raise ProviderError("Local audio currently requires a little-endian host")
        if self.driver is None:
            import sounddevice
            self.driver = sounddevice
        self._loop = asyncio.get_running_loop()
        try:
            self.driver.check_input_settings(device=self.input_device, channels=1, dtype="int16", samplerate=self.rate)
            self.driver.check_output_settings(device=self.output_device, channels=1, dtype="int16", samplerate=self.rate)
            self._stream = self.driver.RawStream(
                samplerate=self.rate, blocksize=0, device=(self.input_device, self.output_device),
                channels=(1, 1), dtype="int16", latency=.2, callback=self._callback,
            )
            self._last_capture_at = time.monotonic()
            self._stream.start()
        except Exception as exc:
            if self._stream:
                self._stream.close()
                self._stream = None
            raise ProviderError("Cannot open microphone/speaker; check device IDs, 32kHz support and microphone permission (" + type(exc).__name__ + ")") from None
        if self.on_event:
            self.on_event("audio_open", echo_mode=self.echo_mode, sample_rate=self.rate)

    def request_stop(self):
        self._stop.set()

    async def audio(self):
        deadline = time.monotonic() + self.max_seconds
        try:
            while not self._stop.is_set() and time.monotonic() < deadline:
                if self._error:
                    if self.on_event:
                        self.on_event("audio_failed", reason="capture_overrun", timing_reliable=False)
                    raise ProviderError(self._error)
                try:
                    frame = self._queue.get_nowait()
                except queue.Empty:
                    if not self._stream.active or (self._last_capture_at is not None and time.monotonic() - self._last_capture_at > 3):
                        if self.on_event:
                            self.on_event("audio_failed", reason="capture_stalled", timing_reliable=False)
                        raise ProviderError("Audio device stopped delivering samples; restart the session")
                    await asyncio.sleep(.01)
                    continue
                # Metering and warnings stay off the realtime PortAudio callback.
                samples = memoryview(frame.pcm).cast("h")
                self.current_peak = max((abs(samples[i]) for i in range(0, len(samples), 16)), default=0)
                self.input_peak = max(self.input_peak, self.current_peak)
                now = time.monotonic()
                if self.on_event and (self.input_overflows != self._reported_overflows or self.output_underflows != self._reported_underflows):
                    self.on_event("audio_warning", reason="input_overflow_or_output_underflow", timing_reliable=False,
                                  input_overflows=self.input_overflows, output_underflows=self.output_underflows)
                    self._reported_overflows, self._reported_underflows = self.input_overflows, self.output_underflows
                if self.on_event and now - self._last_level_at >= .1:
                    self._last_level_at = now
                    self.on_event("audio_level", peak=round(self.current_peak / 32768, 4),
                                  gated=self.echo_mode == "speaker" and now < self._gate_until,
                                  timing_reliable=self.timing_reliable,
                                  captured_seconds=round(self.captured_samples / self.rate, 3))
                yield frame
        finally:
            self.request_stop()
            if self.on_event:
                self.on_event("audio_input_ended")

    async def play_audio(self, pcm, sample_rate):
        if sample_rate != self.rate or not pcm or len(pcm) % 2:
            raise ValueError("Playback must be nonempty PCM16 mono 32000Hz")
        if self._stream is None or not self._stream.active:
            raise ProviderError("Audio stream is not running")
        if self._playback is not None:
            raise ProviderError("Audio playback is already active")
        playback = Playback(pcm, asyncio.Event())
        self._playback = playback
        try:
            await asyncio.wait_for(playback.done.wait(), len(pcm) / 64000 + 3)
            if playback.ends_at:
                await asyncio.sleep(max(0, playback.ends_at - time.monotonic()))
        except asyncio.CancelledError:
            playback.cancelled.set()
            raise
        except TimeoutError:
            playback.cancelled.set()
            raise ProviderError("Speaker playback timed out") from None

    async def stop_speaking(self):
        playback = self._playback
        if playback:
            playback.cancelled.set()

    async def leave(self):
        self.request_stop()
        await self.stop_speaking()
        if self._stream:
            stream, self._stream = self._stream, None
            # A stuck driver must not block the event loop or cancellation cleanup.
            try:
                async with asyncio.timeout(2):
                    await asyncio.to_thread(stream.abort)
                    await asyncio.to_thread(stream.close)
            except TimeoutError:
                if self.on_event:
                    self.on_event("audio_cleanup_failed", reason="driver_timeout")
                raise ProviderError("Audio driver did not close within two seconds") from None

    def diagnostics(self):
        return {"captured_seconds": round(self.captured_samples / self.rate, 3),
                "echo_gated_seconds": round(self.gated_samples / self.rate, 3),
                "input_overflows": self.input_overflows, "output_underflows": self.output_underflows,
                "input_peak": self.input_peak, "echo_mode": self.echo_mode, "timing_reliable": self.timing_reliable,
                "callback_count": self.callback_count, "last_block_frames": self.last_block_frames,
                "max_callback_gap_ms": self.max_callback_gap_ms}

    @property
    def timing_reliable(self):
        return self.input_overflows == 0 and self.output_underflows == 0
