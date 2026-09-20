from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass(frozen=True)
class TranscriptEvent:
    meeting_id: str
    event_id: str
    timestamp_ms: int
    text: str
    speaker: str | None = None
    is_final: bool = True
    source: Literal["human", "bot"] = "human"
    speaker_id: str | None = None


@dataclass
class Task:
    task_id: str
    meeting_id: str
    request: str
    context: list[TranscriptEvent]
    status: Literal["queued", "running", "completed", "failed"] = "queued"
    result: str | None = None
    error: str | None = None
    sources: list[str] = field(default_factory=list)


class MeetingAdapter(Protocol):
    async def join(self, meeting_url: str) -> None: ...
    async def speak(self, text: str) -> None: ...
    async def stop_speaking(self) -> None: ...
    async def leave(self) -> None: ...
