"""Primitive orchestration: keep input live while the one response task runs."""
import asyncio
import time
from collections import deque
from dataclasses import asdict

from .wake import ADDRESS, CANCEL, addressed_request


class Primitive:
    def __init__(self, meeting, ears, mouth, *, reply="我在。", brain=None, mode="simulate"):
        self.meeting, self.ears, self.mouth = meeting, ears, mouth
        self.reply, self.brain, self.mode = reply, brain, mode
        self.context = deque(maxlen=50)
        self.events = []
        self.seen = set()
        self.response_task = None
        self.started = time.monotonic()

    def log(self, kind, **fields):
        self.events.append({"type": kind, "elapsed_ms": round((time.monotonic() - self.started) * 1000), **fields})

    async def respond(self, snapshot, cached, detected):
        try:
            self.log("reply", text=self.reply, cached=True,
                     detection_to_output_call_ms=round((time.monotonic() - detected) * 1000))
            await self.meeting.play_audio(cached, 32000)
            if self.brain:
                answer = await self.brain.answer(snapshot)
                audio = await self.mouth.synthesize(answer)
                self.log("answer", text=answer)
                await self.meeting.play_audio(audio, 32000)
            self.log("response_completed")
        except asyncio.CancelledError:
            self.log("response_cancelled")
            raise
        except Exception as exc:
            # Do not copy HTTP response bodies/credentials into logs.
            self.log("response_failed", error_type=type(exc).__name__)

    async def cancel_response(self):
        if self.response_task and not self.response_task.done():
            self.response_task.cancel()
            await self.meeting.stop_speaking()
            await asyncio.gather(self.response_task, return_exceptions=True)
            self.response_task = None

    async def accept(self, event, cached):
        key = (event.meeting_id, event.event_id)
        if not event.is_final or key in self.seen:
            self.log("ignored", reason="partial_or_duplicate", event_id=event.event_id)
            return
        self.seen.add(key)
        if len(self.seen) > 10000:
            raise RuntimeError("Primitive transcript limit reached; restart the session")
        self.log("transcript", **asdict(event))
        if event.source == "bot":
            return
        self.context.append(event.text)
        address = ADDRESS.match(event.text)
        rest = event.text[address.end():].strip(" ,，:：") if address else event.text.strip()
        if CANCEL.search(rest):
            await self.cancel_response()
            return
        if addressed_request(event.text) is None:
            return
        if self.response_task and not self.response_task.done():
            self.log("ignored", reason="response_busy", event_id=event.event_id)
            return
        self.log("wake", event_id=event.event_id)
        self.response_task = asyncio.create_task(self.respond(list(self.context), cached, time.monotonic()))

    async def run(self):
        self.log("session_started", mode=self.mode)
        # Resolve TTS credentials/voice failures before entering the meeting.
        cached = await self.mouth.synthesize(self.reply)
        self.log("reply_prepared", bytes=len(cached))
        try:
            await self.meeting.join()
            self.log("meeting_joined", simulated=self.mode in {"simulate", "hybrid-tts"})
            async for event in self.ears.transcribe(self.meeting.audio()):
                await self.accept(event, cached)
            if self.response_task:
                await self.response_task
        finally:
            await self.cancel_response()
            await self.meeting.leave()
            self.log("meeting_left")
        return {"mode": self.mode, "events": self.events,
                "response_failures": sum(e["type"] == "response_failed" for e in self.events),
                "limitations": ["Meeting and transcripts are simulated; TTS is live only in hybrid-tts mode.",
                                "Timing is process orchestration timing, not real wake-to-audible latency.",
                                "Real Zoom native adapter and full meeting acceptance are pending SDK setup."]}
