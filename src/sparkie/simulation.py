"""Scripted fakes, intentionally offline. Silence is not synthesized speech."""
import asyncio
import wave
from pathlib import Path

from .audio import AudioFrame
from .contracts import TranscriptEvent


class SimulatedMeeting:
    def __init__(self, events: list[TranscriptEvent], output: Path, interval=0.08, playback=0.3, audio_prefix="simulated-reply"):
        self.events, self.output = events, output
        self.interval, self.playback = interval, playback
        self.audio_prefix = audio_prefix
        self.joined = False
        self.playing = False
        self.stop = asyncio.Event()
        self.outputs = []
        self.inputs_while_playing = 0

    async def join(self):
        self.joined = True

    async def audio(self):
        if not self.joined:
            raise RuntimeError("Simulated meeting is not joined")
        for sequence, _ in enumerate(self.events):
            await asyncio.sleep(self.interval)
            if self.playing:
                self.inputs_while_playing += 1
            yield AudioFrame(sequence, b"\0" * 1280)

    async def play_audio(self, pcm: bytes, sample_rate: int):
        if not self.joined:
            raise RuntimeError("Cannot play into a closed meeting")
        self.output.mkdir(parents=True, exist_ok=True)
        path = self.output / f"{self.audio_prefix}-{len(self.outputs) + 1}.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm)
        self.outputs.append(str(path))
        self.playing = True
        self.stop.clear()
        try:
            await asyncio.wait_for(self.stop.wait(), timeout=self.playback)
        except TimeoutError:
            pass
        finally:
            self.playing = False

    async def stop_speaking(self):
        self.stop.set()

    async def leave(self):
        self.joined = False


class ScriptedDeepgram:
    def __init__(self, events):
        self.events = events

    async def transcribe(self, frames):
        async for frame in frames:
            # Fixture supplies expected text; no speech recognition is taking place.
            yield self.events[frame.sequence]


class SimulatedSpeech:
    async def synthesize(self, text: str) -> bytes:
        await asyncio.sleep(0)
        return b"\0" * 19200  # 300 ms of silence, clearly labeled in the output.
