"""Primitive orchestration: keep input live while the one response task runs."""
import asyncio
import time
from collections import deque
from dataclasses import asdict

from .wake import ADDRESS, CANCEL, addressed_request


class Primitive:
    def __init__(self, meeting, ears, mouth, *, reply="我在。", brain=None, mode="simulate", event_sink=None,
                 question_reply="Let me think for a moment."):
        self.meeting, self.ears, self.mouth = meeting, ears, mouth
        self.reply, self.brain, self.mode = reply, brain, mode
        self.question_reply = question_reply
        self.question_audio = None
        self.context = deque(maxlen=50)
        self.events = []
        self.seen = set()
        self.response_task = None
        self.started = time.monotonic()
        self.event_sink = event_sink

    def log(self, kind, **fields):
        event = {"type": kind, "elapsed_ms": round((time.monotonic() - self.started) * 1000), **fields}
        self.events.append(event)
        if self.event_sink:
            self.event_sink(event)

    def playback_timing(self, phase, response_id, detected, utterance_end_at):
        played_at = getattr(self.meeting, "last_playback_started_at", None)
        if played_at is None:
            return
        if not getattr(self.meeting, "timing_reliable", True):
            self.log("playback_timing_unavailable", phase=phase, response_id=response_id,
                     reason="audio_overflow_or_underflow")
            return
        metrics = {"detection_to_dac_estimate_ms": round((played_at - detected) * 1000)}
        if utterance_end_at is not None:
            metrics["utterance_end_to_dac_estimate_ms"] = round((played_at - utterance_end_at) * 1000)
        self.log("playback_timing", phase=phase, response_id=response_id, **metrics)

    async def generate_answer(self, snapshot, response_id, detected):
        started = time.monotonic()
        self.log("thinking", response_id=response_id, context_entries=len(snapshot))
        answer = await self.brain.answer(snapshot)
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Reasoning backend returned an empty answer")
        answer = answer.strip()
        # Publish text before synthesis so a voice failure doesn't hide a valid answer.
        self.log("answer", response_id=response_id, text=answer,
                 inference_ms=round((time.monotonic() - started) * 1000),
                 detection_to_answer_text_ms=round((time.monotonic() - detected) * 1000))
        self.context.append("[Sparkie answer, not a participant decision] " + answer)
        return answer

    async def respond(self, snapshot, cached, detected, utterance_end_at=None, response_id=None, answer_requested=True, reply_text=None):
        inference = None
        phase = "acknowledgement"
        try:
            if self.brain and answer_requested:
                # Start reasoning while the cached acknowledgement plays.
                inference = asyncio.create_task(self.generate_answer(snapshot, response_id, detected))
            self.log("reply", response_id=response_id, text=self.reply if reply_text is None else reply_text, cached=True,
                     detection_to_output_call_ms=round((time.monotonic() - detected) * 1000))
            await self.meeting.play_audio(cached, 32000)
            self.playback_timing("acknowledgement", response_id, detected, utterance_end_at)
            if inference:
                phase = "reasoning"
                answer = await inference
                phase = "answer_synthesis"
                self.log("answer_synthesis", response_id=response_id)
                synthesis_started = time.monotonic()
                audio = await self.mouth.synthesize(answer)
                self.log("answer_audio_ready", response_id=response_id,
                         synthesis_ms=round((time.monotonic() - synthesis_started) * 1000))
                phase = "answer_playback"
                self.log("answer_playing", response_id=response_id)
                await self.meeting.play_audio(audio, 32000)
                self.playback_timing("answer", response_id, detected, utterance_end_at)
                self.log("answer_completed", response_id=response_id,
                         utterance_end_to_answer_completed_ms=round((time.monotonic() - utterance_end_at) * 1000) if utterance_end_at is not None else None,
                         detection_to_answer_completed_ms=round((time.monotonic() - detected) * 1000))
            self.log("response_completed", response_id=response_id)
        except asyncio.CancelledError:
            self.log("response_cancelled", response_id=response_id, phase=phase)
            raise
        except Exception as exc:
            # Do not copy HTTP response bodies/credentials into logs.
            self.log("response_failed", response_id=response_id, phase=phase, error_type=type(exc).__name__)
        finally:
            if inference:
                if not inference.done():
                    inference.cancel()
                await asyncio.gather(inference, return_exceptions=True)

    async def cancel_response(self):
        if self.response_task and not self.response_task.done():
            self.response_task.cancel()
            try:
                await self.meeting.stop_speaking()
            finally:
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
        self.context.append(f"[{event.speaker} ({event.speaker_id}), {event.timestamp_ms} ms] {event.text}"
                            if event.speaker_id else event.text)
        address = ADDRESS.match(event.text)
        rest = event.text[address.end():].strip(" ,，:：") if address else event.text.strip()
        if CANCEL.search(rest):
            await self.cancel_response()
            return
        request = addressed_request(event.text)
        if request is None:
            self.log("ignored", reason="not_addressed_request", event_id=event.event_id)
            return
        if self.response_task and not self.response_task.done():
            self.log("ignored", reason="response_busy", event_id=event.event_id)
            return
        self.log("wake", event_id=event.event_id, response_id=event.event_id,
                 answer_requested=bool(self.brain and request))
        origin = getattr(self.meeting, "audio_origin", None)
        utterance_end_at = origin + event.timestamp_ms / 1000 if origin is not None else None
        reply_text = self.reply
        if self.brain and request and self.question_audio is not None:
            cached, reply_text = self.question_audio, self.question_reply
        self.response_task = asyncio.create_task(self.respond(list(self.context), cached, time.monotonic(),
                                                                utterance_end_at, event.event_id, bool(request), reply_text))

    async def run(self):
        self.log("session_started", mode=self.mode, response_mode="qa" if self.brain else "wake")
        # Resolve TTS credentials/voice failures before entering the meeting.
        cached = await self.mouth.synthesize(self.reply)
        self.log("reply_prepared", bytes=len(cached))
        if self.brain:
            self.question_audio = (cached if self.question_reply == self.reply
                                   else await self.mouth.synthesize(self.question_reply))
            self.log("reply_prepared", purpose="question", bytes=len(self.question_audio))
        try:
            await self.meeting.join()
            self.log("meeting_joined", simulated=self.mode in {"simulate", "hybrid-tts"})
            async for event in self.ears.transcribe(self.meeting.audio()):
                await self.accept(event, cached)
            if self.response_task:
                await self.response_task
        finally:
            try:
                await self.cancel_response()
            finally:
                await self.meeting.leave()
                self.log("meeting_left")
        return self.report()

    def report(self):
        limitations = []
        if self.mode == "local-audio":
            limitations.extend(["Speaker mode replaces input with silence during playback and echo tail; voice interruption is unavailable in that window.",
                                "DAC latency is an audio-device timestamp estimate, not an independently measured acoustic latency."])
        elif self.mode == "zoom-audio":
            limitations = ["Input is gated during playback plus 350 ms; voice interruption is unavailable in that window.",
                           "Playback completion means frames accepted by Zoom SDK; remote audible latency is not measured.",
                           "Same-account development path; macOS remote audibility, long meetings and reconnection still require acceptance."]
        else:
            limitations.extend(["Meeting and transcripts are simulated; TTS is live only in hybrid-tts mode.",
                                "Timing is process orchestration timing, not real wake-to-audible latency."])
        if self.mode == "zoom-audio" and hasattr(self.meeting, 'speaker_name'):
            limitations[0] = ("SDK self track excluded; acoustic echo from other participants remains possible. "
                              "Speaker identity represents a Zoom endpoint, not people sharing one microphone.")
            limitations.append("Participant timestamps use the SDK media clock with a callback-time fallback; live events arrive in provider completion order.")
        return {"transcript": sorted((e for e in self.events if e['type'] == 'transcript'),
                                    key=lambda e: (e['timestamp_ms'], e['event_id'])),
                "mode": self.mode, "response_mode": "qa" if self.brain else "wake", "events": self.events,
                "response_failures": sum(e["type"] == "response_failed" for e in self.events),
                "limitations": limitations}
