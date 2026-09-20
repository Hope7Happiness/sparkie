"""Agent runtime: observe meeting events, emit actions, sync artifacts to the bus.

Routing is heuristic for the MVP — the same action vocabulary
(IGNORE / RESPOND / CREATE_TASK / PRESENT_ARTIFACT) can later be driven by an LLM
without changing the store or the bus. The runtime knows nothing about Zoom;
adapters ingest TranscriptEvents and consume RESPOND actions.
"""
import asyncio
from dataclasses import dataclass, field
import re
from uuid import uuid4

from .contracts import TranscriptEvent
from .wake import addressed_request

_MARKDOWN_NOISE = re.compile(r"[*_`]+")


def artifact_meta(markdown):
    """Derive a display title and one-line summary from a markdown answer:
    first heading wins for the title, else the first prose line."""
    title = summary = None
    in_fence = False
    for line in str(markdown or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped:
            continue
        if title is None and stripped.startswith("#"):
            title = stripped.lstrip("#").strip()
            continue
        if summary is None and not stripped.startswith(("#", "|", "- ", "* ", ">")):
            summary = stripped
        if title and summary:
            break
    clean = lambda text: _MARKDOWN_NOISE.sub("", text or "").strip()
    return (clean(title) or clean(summary) or "artifact")[:80], \
        clean(summary or title)[:400]


RESEARCH = re.compile(
    r"\b(research|look\s*up|find\s+out|check\s+(?:if|whether)|search|dig\s+into"
    r"|draft|write|prepare|summari[sz]e|append|revise)\b"
    r"|(?:turn|convert)\s+\S+\s+into|\b(?:add|update)\s+(?:the|that|this|our|those)\b"
    r"|调研|调查|查一下|找找|写一?份|写个|总结", re.I)
PRESENT = re.compile(r"show\s+(?:us|me|everyone|the)\b|present|display|给大家看|展示|投屏", re.I)


@dataclass
class Action:
    kind: str
    payload: dict = field(default_factory=dict)

    def as_event(self):
        return {"action": self.kind, **self.payload}


class AgentRuntime:
    """Per-workspace observe → action dispatch. worker(instruction, transcript) is an
    async callable returning {type, title, summary, content} for the artifact."""

    def __init__(self, store, bus, worker=None, greeting="I'm here."):
        self.store, self.bus, self.worker = store, bus, worker
        self.greeting = greeting
        self.runners = {}
        self.mirrored_artifacts = set()

    def ingest(self, workspace_id, event: TranscriptEvent, live_mirror=False):
        """Persist one meeting event, broadcast the utterance, and dispatch actions.
        Returns the action list so adapters/tests can see what the agent decided."""
        row_id = self.store.append_transcript(workspace_id, event)
        self.bus.publish(workspace_id, {
            "type": "utterance", "transcript_id": row_id, "event_id": event.event_id,
            "speaker": event.speaker, "text": event.text,
            "timestamp_ms": event.timestamp_ms, "is_final": event.is_final,
            "source": event.source})
        actions = self.observe(workspace_id, event, row_id) \
            if event.is_final and event.source == "human" else [Action("IGNORE")]
        if live_mirror:
            # A live session already answered/created its own tasks; only the
            # presentation path stays so "show us" still drives every screen.
            actions = [a for a in actions if a.kind == "PRESENT_ARTIFACT"] or \
                [Action("IGNORE")]
        for action in actions:
            self.dispatch(workspace_id, action)
        return actions

    def observe(self, workspace_id, event, transcript_id):
        request = addressed_request(event.text)
        if request is None:
            return [Action("IGNORE")]
        if not request:
            return [Action("RESPOND", {"text": self.greeting, "request": ""})]
        if PRESENT.search(request):
            artifact_id = self.store.latest_artifact(workspace_id)
            if artifact_id:
                return [Action("PRESENT_ARTIFACT", {"artifact_id": artifact_id})]
            return [Action("RESPOND", {"text": "I don't have anything to show yet.", "request": request})]
        if RESEARCH.search(request):
            return [Action("CREATE_TASK", {"instruction": request, "transcript_id": transcript_id})]
        return [Action("RESPOND", {"request": request})]

    def dispatch(self, workspace_id, action):
        if action.kind == "RESPOND":
            # Voice adapters subscribe and turn this into speech; the runtime only
            # records the decision so panels can show that Sparkie is answering.
            self.bus.publish(workspace_id, {"type": "agent.respond", **action.payload})
        elif action.kind == "CREATE_TASK":
            instruction = action.payload["instruction"]
            task_id = self.store.create_task(
                workspace_id, instruction, action.payload.get("transcript_id"))
            self.bus.publish(workspace_id, {
                "type": "task.started", "task_id": task_id, "instruction": instruction})
            self.runners[task_id] = asyncio.get_running_loop().create_task(
                self._run_task(workspace_id, task_id, instruction))
        elif action.kind == "PRESENT_ARTIFACT":
            artifact_id = action.payload["artifact_id"]
            self.store.set_active_artifact(workspace_id, artifact_id)
            self.bus.publish(workspace_id, {
                "type": "artifact.present", "artifact_id": artifact_id})

    async def _run_task(self, workspace_id, task_id, instruction):
        try:
            if self.worker is None:
                raise RuntimeError("no_worker")
            artifact = await self.worker(instruction, self.store.transcript(workspace_id))
        except Exception as exc:
            self.store.finish_task(task_id, "failed", error=type(exc).__name__)
            self.bus.publish(workspace_id, {
                "type": "task.failed", "task_id": task_id, "error_type": type(exc).__name__})
            return
        artifact_id = self.store.create_artifact(
            workspace_id, task_id=task_id, type=artifact.get("type", "report"),
            title=artifact.get("title", instruction[:80]),
            summary=artifact.get("summary", ""), content=artifact.get("content"))
        self.store.finish_task(task_id, "completed", result=artifact.get("summary", ""))
        self.bus.publish(workspace_id, {"type": "task.completed", "task_id": task_id})
        self.bus.publish(workspace_id, {
            "type": "artifact.ready", "artifact_id": artifact_id,
            "task_id": task_id, "title": artifact.get("title", ""),
            "summary": artifact.get("summary", "")})
        # A report produced after the meeting ended presents itself.
        if self.store.get_workspace(workspace_id)["status"] == "ended":
            self.dispatch(workspace_id, Action("PRESENT_ARTIFACT", {"artifact_id": artifact_id}))

    def mirror_task(self, workspace_id, fields):
        """Mirror a live session's TaskCenter job lifecycle into the workspace."""
        task_id = fields.get("task_id")
        if not task_id or not isinstance(fields.get("status"), str):
            return
        instruction = fields.get("instruction") or fields.get("request")
        error = fields.get("error") or fields.get("error_type")
        self.store.upsert_task(workspace_id, task_id, instruction,
                               fields["status"], result=fields.get("result"),
                               error=error)
        self.bus.publish(workspace_id, {
            "type": "task.updated", "task_id": task_id, "instruction": instruction,
            "status": fields["status"], "error_type": error,
            "progress": fields.get("progress")})
        result = fields.get("result")
        if fields["status"] == "completed" and result and task_id not in self.mirrored_artifacts:
            self.mirrored_artifacts.add(task_id)
            title, summary = artifact_meta(str(result))
            artifact_id = self.store.create_artifact(
                workspace_id, task_id=task_id, type="report",
                title=title, summary=summary,
                content={"markdown": str(result)})
            self.bus.publish(workspace_id, {
                "type": "artifact.ready", "artifact_id": artifact_id,
                "task_id": task_id, "title": title, "summary": summary})

    def cancel_task(self, workspace_id, task_id):
        runner = self.runners.get(task_id)
        if runner and not runner.done():
            runner.cancel()
        self.store.finish_task(task_id, "failed", error="cancelled")
        self.bus.publish(workspace_id, {"type": "task.cancelled", "task_id": task_id})

    REPORT_INSTRUCTION = ("Summarize this meeting using only the transcript: overview, "
                          "key discussion points, decisions, action items. Reply in Markdown.")

    def end_meeting(self, workspace_id):
        """Mark the meeting ended and queue a report artifact through the task pipeline."""
        self.store.set_status(workspace_id, "ended")
        self.bus.publish(workspace_id, {"type": "meeting.ended", "status": "ended"})
        if self.worker is None or not self.store.transcript(workspace_id):
            return
        self.dispatch(workspace_id, Action("CREATE_TASK", {"instruction": self.REPORT_INSTRUCTION}))

    async def drain(self):
        if self.runners:
            await asyncio.gather(*self.runners.values(), return_exceptions=True)

    async def close(self):
        for runner in self.runners.values():
            runner.cancel()
        if self.runners:
            await asyncio.gather(*self.runners.values(), return_exceptions=True)


def utterance(workspace_id, text, speaker=None, source="human", is_final=True):
    """Build a TranscriptEvent for adapter ingest (RTMS, Zoom audio, WS demos)."""
    return TranscriptEvent(meeting_id=workspace_id, event_id=f"e_{uuid4().hex[:10]}",
                           timestamp_ms=0, text=text, speaker=speaker,
                           is_final=is_final, source=source)
