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

    def test_reset_clears_session_content_but_keeps_the_workspace(self):
        ws = self.store.resolve_or_create("zoom_uuid", "7271847043")
        self.store.append_transcript(ws, utterance(ws, "hi", "Alice"))
        task_id = self.store.create_task(ws, "research x")
        artifact_id = self.store.create_artifact(ws, task_id=task_id)
        self.store.set_active_artifact(ws, artifact_id)
        self.store.set_status(ws, "ended")
        self.store.reset(ws)
        snapshot = self.store.snapshot(ws)
        assert snapshot["workspace"]["status"] == "live"
        assert snapshot["workspace"]["external_id"] == "7271847043"
        assert snapshot["transcript"] == [] and snapshot["tasks"] == []
        assert snapshot["artifacts"] == []
        assert snapshot["state"]["active_artifact_id"] is None

    def test_upsert_task_mirrors_external_task_ids(self):
        ws = self.store.resolve_or_create("zoom_uuid", "u2")
        self.store.upsert_task(ws, "zoom-task-1", "weather in Boston", "queued")
        self.store.upsert_task(ws, "zoom-task-1", "weather in Boston", "running")
        self.store.upsert_task(ws, "zoom-task-1", "weather in Boston", "completed",
                               result="sunny")
        task = self.store.snapshot(ws)["tasks"][0]
        assert task["task_id"] == "zoom-task-1" and task["status"] == "completed"
        assert task["result"] == "sunny" and task["finished_at"] is not None


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

    async def test_mirror_task_broadcasts_live_session_lifecycle(self):
        fields = {"task_id": "t_live_1", "request": "check Boston weather",
                  "status": "running"}
        self.runtime.mirror_task(self.ws, fields)
        self.runtime.mirror_task(self.ws, {**fields, "status": "completed"})
        first = await asyncio.wait_for(self.queue.get(), 5)
        second = await asyncio.wait_for(self.queue.get(), 5)
        assert [first["status"], second["status"]] == ["running", "completed"]
        assert all(e["type"] == "task.updated" for e in (first, second))
        task = self.store.snapshot(self.ws)["tasks"][0]
        assert task["task_id"] == "t_live_1" and task["instruction"] == "check Boston weather"

    async def test_mirror_task_completed_creates_presentable_artifact(self):
        self.runtime.mirror_task(self.ws, {"task_id": "j1", "request": "weather",
                                         "status": "running"})
        await asyncio.wait_for(self.queue.get(), 5)
        self.runtime.mirror_task(self.ws, {"task_id": "j1", "request": "weather",
                                           "status": "completed", "result": "sunny, 56F"})
        events = await collect(self.queue, "artifact.ready")
        assert events[-1]["task_id"] == "j1"
        artifact = self.store.get_artifact(events[-1]["artifact_id"])
        assert "sunny" in artifact["content"]["markdown"]

    async def test_live_mirror_filters_actions_but_keeps_present(self):
        actions = self.runtime.ingest(
            self.ws, utterance(self.ws, "Sparkie, research X"), live_mirror=True)
        assert [a.kind for a in actions] == ["IGNORE"]
        assert self.store.snapshot(self.ws)["tasks"] == []
        self.store.create_artifact(self.ws, title="report")
        actions = self.runtime.ingest(
            self.ws, utterance(self.ws, "Sparkie, show us the results"), live_mirror=True)
        assert [a.kind for a in actions] == ["PRESENT_ARTIFACT"]

    async def test_artifact_meta_derives_title_and_summary(self):
        from sparkie.agent_runtime import artifact_meta
        title, summary = artifact_meta(
            "```\nfenced # not a title\n```\n\n# Boston Weather Tonight\n\n"
            "| a | b |\n|---|---|\n\n**52°F**, bring a light jacket.")
        assert title == "Boston Weather Tonight"
        assert summary == "52°F, bring a light jacket."
        title, summary = artifact_meta("# Title\n\nSure!\n\nBody.")
        assert summary == "Sure!"  # first prose line wins
        title, summary = artifact_meta("No headings here, just the answer.")
        assert title == "No headings here, just the answer."

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

    async def test_present_page_serves_self_contained_stage(self):
        workspace = await self.get("/api/meetings/resolve?kind=zoom_uuid&external_id=mtg1")
        ws = workspace["workspace_id"]
        def fetch():
            with urllib.request.urlopen(f"{self.base}/workspaces/{ws}/present") as response:
                return response.headers.get_content_type(), response.read().decode()
        content_type, body = await asyncio.to_thread(fetch)
        assert content_type == "text/html"
        assert ws in body and "/events" in body
        assert "artifact.present" in body and "markdown" in body
        assert self.store.get_workspace("ws_deadbeef") is None
        status = None
        def missing():
            nonlocal status
            try:
                urllib.request.urlopen(f"{self.base}/workspaces/ws_deadbeef/present")
            except urllib.error.HTTPError as exc:
                status = exc.code
        await asyncio.to_thread(missing)
        assert status == 404

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

    async def test_ws_task_update_mirrors_session_job(self):
        workspace = await self.get("/api/meetings/resolve?kind=zoom_uuid&external_id=mtg3")
        ws = workspace["workspace_id"]
        async with connect(f"ws://127.0.0.1:{self.port}/workspaces/{ws}/events") as socket:
            await socket.send(json.dumps(
                {"type": "task_update", "task_id": "job_9", "request": "dig into X",
                 "status": "running"}))
            event = json.loads(await asyncio.wait_for(socket.recv(), 10))
            assert event["type"] == "task.updated" and event["task_id"] == "job_9"
        assert self.store.snapshot(ws)["tasks"][0]["status"] == "running"

    async def test_resolve_reset_clears_and_notifies_subscribers(self):
        workspace = await self.get("/api/meetings/resolve?kind=zoom_uuid&external_id=mtg4")
        ws = workspace["workspace_id"]
        self.store.append_transcript(ws, utterance(ws, "old session", "Alice"))
        async with connect(f"ws://127.0.0.1:{self.port}/workspaces/{ws}/events") as socket:
            again = await self.get(
                "/api/meetings/resolve?kind=zoom_uuid&external_id=mtg4&reset=1")
            assert again["workspace_id"] == ws
            event = json.loads(await asyncio.wait_for(socket.recv(), 10))
            assert event["type"] == "workspace.reset"
        snapshot = await self.get(f"/api/workspaces/{ws}")
        assert snapshot["transcript"] == []

    async def test_browser_cancel_reaches_session_client(self):
        from sparkie.workspace_client import WorkspaceClient
        workspace = await self.get("/api/meetings/resolve?kind=zoom_uuid&external_id=mtg5")
        ws = workspace["workspace_id"]
        client = WorkspaceClient(f"127.0.0.1:{self.port}")
        assert await client.open("zoom_uuid", "mtg5")
        received, got = [], asyncio.Event()
        def on_message(message):
            received.append(message)
            if message.get("type") == "task.cancelled":
                got.set()
        client.on_message = on_message
        try:
            async with connect(f"ws://127.0.0.1:{self.port}/workspaces/{ws}/events") as socket:
                await socket.send(json.dumps({"type": "cancel_task", "task_id": "j7"}))
                await asyncio.wait_for(got.wait(), 10)
            assert received[-1]["task_id"] == "j7"
        finally:
            await client.close()

    async def test_unknown_workspace_socket_is_rejected(self):
        from websockets.exceptions import ConnectionClosed
        with self.assertRaises(ConnectionClosed):
            async with connect(f"ws://127.0.0.1:{self.port}/workspaces/ws_deadbeef/events") as socket:
                await socket.recv()


if __name__ == "__main__":
    unittest.main()
