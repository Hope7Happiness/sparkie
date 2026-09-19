"""Offline event replay. No real meeting, speech, model, or web search."""
import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path

from .contracts import TranscriptEvent


def should_wake(event: TranscriptEvent) -> bool:
    # Deliberately conservative placeholder; owner A must validate on real speech.
    return bool(
        event.is_final
        and event.source == "human"
        and re.match(r"^\s*sparkie\s*[,，:：]\s*\S", event.text, re.IGNORECASE)
        and not re.search(r"没事|不用了|取消|never mind|cancel", event.text, re.IGNORECASE)
    )


def replay(events: list[TranscriptEvent]) -> dict:
    seen = set()
    transcript = []
    replies = []
    for event in events:
        key = (event.meeting_id, event.event_id)
        if not event.is_final or key in seen:
            continue
        seen.add(key)
        transcript.append(asdict(event))
        if should_wake(event):
            replies.append({"event_id": event.event_id, "text": "我在。", "mode": "mock"})
    return {
        "mode": "mock",
        "transcript": transcript,
        "replies": replies,
        "tasks": [],
        "overview": None,
        "key_discussion_points": [],
        "decisions": [],
        "action_items": [],
        "open_questions": [],
        "limitations": ["Offline replay only; semantic summary and real integrations are not implemented."],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("output/meeting.json"))
    args = parser.parse_args()
    events = [TranscriptEvent(**json.loads(line)) for line in args.input.read_text().splitlines() if line.strip()]
    report = replay(events)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"MOCK: {len(report['transcript'])} events, {len(report['replies'])} fixed text replies → {args.output}")


if __name__ == "__main__":
    main()
