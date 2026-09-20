from dataclasses import dataclass
from typing import Literal


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


@dataclass(frozen=True)
class SpeechActivity:
    """Candidate VAD or text-confirmed speech, ordered with final transcripts."""
    phase: Literal["candidate", "started", "stopped"]
    timestamp_ms: int = 0
    speaker_id: str | None = None
    stream_id: str | None = None
