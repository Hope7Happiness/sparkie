"""Audio boundary for replacing the simulated body with the Zoom native SDK."""
from dataclasses import dataclass
from typing import AsyncIterator, Protocol


@dataclass(frozen=True)
class AudioFrame:
    sequence: int
    pcm: bytes  # Signed 16-bit little-endian, mono, headerless.
    sample_rate: int = 32000


class AudioMeeting(Protocol):
    async def join(self) -> None: ...
    def audio(self) -> AsyncIterator[AudioFrame]: ...
    async def play_audio(self, pcm: bytes, sample_rate: int) -> None: ...
    async def stop_speaking(self) -> None: ...
    async def leave(self) -> None: ...
