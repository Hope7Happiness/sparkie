import asyncio
import json
import unittest
import urllib.request

from websockets.asyncio.client import connect

from sparkie.agent_runtime import AgentRuntime, utterance
from sparkie.event_bus import EventBus
from sparkie.workspace import WorkspaceStore
from sparkie.workspace_server import serve_workspace


async def collect(queue, wanted, limit=20):
    events = []
    for _ in range(limit):
        event = await asyncio.wait_for(queue.get(), 5)
        events.append(event)
        if wanted in {e["type"] for e in events}:
            return events
    return events


async def fake_worker(instruction, transcript):
    return {"type": "report", "title": f"Scan: {instruction[:40]}",
            "summary": "test artifact", "content": {"instruction": instruction}}


class WorkspaceStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = WorkspaceStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_resolve_maps_external_ids_to_one_workspace(self):
        first = self.store.resolve_or_create("zoom_uuid", "abc==", "sync")
        assert self.store.resolve_or_create("zoom_uuid", "abc==") == first
        assert self.store.resolve_or_create("meet_id", "abc==") != first
        assert self.store.resolve("zoom_uuid", "missing") is None

    def test_snapshot_has_the_five_design_tables(self):
        ws = self.store.resolve_or_create("zoom_uuid", "u1")
        self.store.append_transcript(ws, utterance(ws, "hello", "Alice"))
        task_id = self.store.create_task(ws, "research x")
        artifact_id = self.store.create_artifact(ws, task_id=task_id, title="t")
        self.store.set_active_artifact(ws, artifact_id)
        snapshot = self.store.snapshot(ws)
        assert snapshot["workspace"]["workspace_id"] == ws
        assert len(snapshot["transcript"]) == 1
        assert snapshot["tasks"][0]["instruction"] == "research x"
        assert snapshot["artifacts"][0]["title"] == "t"
        assert snapshot["state"]["active_artifact_id"] == artifact_id


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = WorkspaceStore(":memory:")
        self.bus = EventBus()
        self.runtime = AgentRuntime(self.store, self.bus, fake_worker)
        self.ws = self.store.resolve_or_create("zoom_uuid", "u1")
        self.queue = self.bus.subscribe(self.ws)

    async def asyncTearDown(self):
        await self.runtime.close()
        self.store.close()

    def types(self, events):
        return [event["type"] for event in events]

    async def test_unaddressed_speech_is_ignored_but_still_broadcast(self):
        actions = self.runtime.ingest(self.ws, utterance(self.ws, "random chatter"))
        assert [a.kind for a in actions] == ["IGNORE"]
        events = await collect(self.queue, "utterance")
        assert events[0]["type"] == "utterance" and events[0]["text"] == "random chatter"

    async def test_wake_question_responds(self):
        actions = self.runtime.ingest(
            self.ws, utterance(self.ws, "Sparkie, what is a WebSocket?"))
        assert [a.kind for a in actions] == ["RESPOND"]
        events = await collect(self.queue, "agent.respond")
        assert events[-1]["request"] == "what is a WebSocket"

    async def test_research_creates_task_then_artifact_ready(self):
        actions = self.runtime.ingest(
            self.ws, utterance(self.ws, "Sparkie, research whether this has been done"))
        assert [a.kind for a in actions] == ["CREATE_TASK"]
        events = await collect(self.queue, "artifact.ready")
        types = self.types(events)
        assert "task.started" in types and "task.completed" in types
        assert self.store.latest_artifact(self.ws) is not None

    async def test_show_us_presents_latest_artifact(self):
        self.runtime.ingest(self.ws, utterance(self.ws, "Sparkie, research prior work"))
        await collect(self.queue, "artifact.ready")
        actions = self.runtime.ingest(self.ws, utterance(self.ws, "Sparkie, show us what you found"))
        assert [a.kind for a in actions] == ["PRESENT_ARTIFACT"]
        events = await collect(self.queue, "artifact.present")
        artifact_id = events[-1]["artifact_id"]
        assert self.store.get_state(self.ws)["active_artifact_id"] == artifact_id

    async def test_present_with_no_artifacts_responds_instead(self):
        actions = self.runtime.ingest(self.ws, utterance(self.ws, "Sparkie, show us the results"))
        assert [a.kind for a in actions] == ["RESPOND"]

    async def test_end_meeting_publishes_and_presents_report(self):
        self.runtime.ingest(self.ws, utterance(self.ws, "we decided on three pipelines"))
        self.runtime.end_meeting(self.ws)
        assert self.store.get_workspace(self.ws)["status"] == "ended"
        events = await collect(self.queue, "artifact.present")
        types = self.types(events)
        assert "meeting.ended" in types and "task.started" in types and "artifact.ready" in types

    async def test_end_meeting_without_transcript_skips_report(self):
        self.runtime.end_meeting(self.ws)
        events = await collect(self.queue, "meeting.ended")
        assert "task.started" not in self.types(events)

    async def test_cancel_task(self):
        async def slow_worker(instruction, transcript):
            await asyncio.sleep(60)
        self.runtime.worker = slow_worker
        self.runtime.ingest(self.ws, utterance(self.ws, "Sparkie, research something slow"))
        task_id = next(iter(self.runtime.runners))
        self.runtime.cancel_task(self.ws, task_id)
        events = await collect(self.queue, "task.cancelled")
        assert events[-1]["task_id"] == task_id

    async def test_bot_utterances_never_trigger_actions(self):
        actions = self.runtime.ingest(
            self.ws, utterance(self.ws, "Sparkie, research this", source="bot"))
        assert [a.kind for a in actions] == ["IGNORE"]

    async def test_two_clients_receive_the_same_stream(self):
        second = self.bus.subscribe(self.ws)
        self.bus.publish(self.ws, {"type": "artifact.present", "artifact_id": "art_x"})
        for queue in (self.queue, second):
            event = await asyncio.wait_for(queue.get(), 5)
            assert event["type"] == "artifact.present" and event["workspace_id"] == self.ws


class WorkspaceServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = WorkspaceStore(":memory:")
        self.bus = EventBus()
        self.runtime = AgentRuntime(self.store, self.bus, fake_worker)
        self.server = await serve_workspace(self.store, self.bus, self.runtime, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"

    async def asyncTearDown(self):
        self.server.close()
        await self.runtime.close()
        self.store.close()

    async def get(self, path):
        def fetch():
            with urllib.request.urlopen(self.base + path) as response:
                return json.loads(response.read())
        # Blocking HTTP runs off the event loop the test server shares.
        return await asyncio.to_thread(fetch)

    async def test_resolve_then_ws_ingest_then_snapshot(self):
        workspace = await self.get("/api/meetings/resolve?kind=zoom_uuid&external_id=mtg1&title=t")
        ws = workspace["workspace_id"]
        async with connect(f"ws://127.0.0.1:{self.port}/workspaces/{ws}/events") as socket:
            await socket.send(json.dumps(
                {"type": "utterance", "speaker": "Alice",
                 "text": "Sparkie, research related work"}))
            seen = set()
            for _ in range(20):
                event = json.loads(await asyncio.wait_for(socket.recv(), 10))
                seen.add(event["type"])
                if "artifact.ready" in seen:
                    break
            assert {"utterance", "task.started", "task.completed", "artifact.ready"} <= seen
        snapshot = await self.get(f"/api/workspaces/{ws}")
        assert snapshot["workspace"]["title"] == "t"
        assert len(snapshot["artifacts"]) == 1
        listing = await self.get("/api/workspaces")
        assert any(w["workspace_id"] == ws and w["transcript_count"] >= 1
                   for w in listing["workspaces"])

    async def test_ws_end_meeting_triggers_report_flow(self):
        workspace = await self.get("/api/meetings/resolve?kind=zoom_uuid&external_id=mtg2")
        ws = workspace["workspace_id"]
        async with connect(f"ws://127.0.0.1:{self.port}/workspaces/{ws}/events") as socket:
            await socket.send(json.dumps({"type": "utterance", "text": "short meeting"}))
            await socket.send(json.dumps({"type": "end_meeting"}))
            seen = set()
            for _ in range(20):
                event = json.loads(await asyncio.wait_for(socket.recv(), 10))
                seen.add(event["type"])
                if "artifact.present" in seen:
                    break
            assert {"meeting.ended", "task.started", "artifact.ready", "artifact.present"} <= seen
        assert self.store.get_workspace(ws)["status"] == "ended"

    async def test_unknown_workspace_socket_is_rejected(self):
        from websockets.exceptions import ConnectionClosed
        with self.assertRaises(ConnectionClosed):
            async with connect(f"ws://127.0.0.1:{self.port}/workspaces/ws_deadbeef/events") as socket:
                await socket.recv()


if __name__ == "__main__":
    unittest.main()
