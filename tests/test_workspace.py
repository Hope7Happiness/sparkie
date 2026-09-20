import asyncio
import json
import sqlite3
import tempfile
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from websockets.asyncio.client import connect

from sparkie.agent_runtime import AgentRuntime, utterance
from sparkie.event_bus import EventBus
from sparkie.workspace import SCHEMA, WorkspaceStore
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


class WorkspaceConfigurationTests(unittest.TestCase):
    def test_worker_uses_environment_unless_explicitly_overridden(self):
        from sparkie.primitive import main
        for options, expected in [([], 'devin'), (['--worker', 'codex'], 'codex')]:
            with self.subTest(options=options), \
                    patch.dict('os.environ', {'SPARKIE_TASK_BACKEND': 'devin'}), \
                    patch('sparkie.primitive.load_dotenv'), \
                    patch('sys.argv', ['sparkie', 'workspace', *options]), \
                    patch('sparkie.workspace_server.workspace_session', new_callable=AsyncMock) as run:
                run.return_value = None
                with self.assertRaises(SystemExit):
                    main()
                self.assertEqual(run.call_args.args[0].worker, expected)


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

    def test_existing_database_migrates_and_generation_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + '/workspace.db'
            legacy = sqlite3.connect(path)
            legacy.executescript(SCHEMA.replace('  generation INTEGER NOT NULL DEFAULT 0,\n', ''))
            legacy.close()
            store = WorkspaceStore(path)
            ws = store.resolve_or_create('zoom_uuid', 'existing')
            self.assertEqual(store.generation(ws), 0)
            store.reset(ws)
            store.close()
            store = WorkspaceStore(path)
            self.assertEqual(store.resolve('zoom_uuid', 'existing'), ws)
            self.assertEqual(store.generation(ws), 1)
            store.close()


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

    async def test_reset_fences_old_worker_result_and_error(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                started, release = asyncio.Event(), asyncio.Event()
                async def worker(instruction, transcript):
                    started.set()
                    await release.wait()
                    if fail:
                        raise RuntimeError('old session failed')
                    return {'title': 'old session result', 'content': {'markdown': 'old'}}
                self.runtime.worker = worker
                self.runtime.ingest(self.ws, utterance(self.ws, 'Sparkie, research old session'))
                await started.wait()
                self.store.reset(self.ws)
                while not self.queue.empty():
                    self.queue.get_nowait()
                release.set()
                await self.runtime.drain()
                snapshot = self.store.snapshot(self.ws)
                self.assertEqual(snapshot['tasks'], [])
                self.assertEqual(snapshot['artifacts'], [])
                self.assertTrue(self.queue.empty())

    async def test_present_with_no_artifacts_responds_instead(self):
        actions = self.runtime.ingest(self.ws, utterance(self.ws, "Sparkie, show us the results"))
        assert [a.kind for a in actions] == ["RESPOND"]

    async def test_reset_cancels_only_its_workers_and_fences_cancellation_resistant_result(self):
        other = self.store.resolve_or_create('zoom_uuid', 'other')
        started, release = asyncio.Event(), asyncio.Event()
        async def worker(instruction, transcript):
            if 'old' in instruction:
                started.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    return {'title': 'late old result'}
            await release.wait()
            return {'title': 'other meeting result'}
        self.runtime.worker = worker
        self.runtime.ingest(self.ws, utterance(self.ws, 'Sparkie, research old'))
        self.runtime.ingest(other, utterance(other, 'Sparkie, research new'))
        await started.wait()
        self.runtime.reset_workspace(self.ws)
        release.set()
        await self.runtime.drain()
        self.assertEqual(self.store.snapshot(self.ws)['artifacts'], [])
        self.assertEqual(len(self.store.snapshot(other)['artifacts']), 1)
        events = []
        while not self.queue.empty():
            events.append(self.queue.get_nowait()['type'])
        self.assertEqual(events[-1], 'workspace.reset')

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

    async def test_workspace_shutdown_closes_persistent_devin_worker(self):
        from sparkie.workspace_server import workspace_session
        worker = SimpleNamespace(close=AsyncMock())
        server = SimpleNamespace(serve_forever=AsyncMock())
        with tempfile.TemporaryDirectory() as directory, \
                patch('sparkie.devin_acp.DevinTaskWorker', return_value=worker), \
                patch('sparkie.workspace_server.serve_workspace', AsyncMock(return_value=server)), \
                patch('builtins.print'):
            args = SimpleNamespace(db=Path(directory) / 'workspace.db', worker='devin', host='127.0.0.1', port=0)
            await workspace_session(args)
        worker.close.assert_awaited_once()

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

    async def test_reset_rejects_old_socket_writes_but_browser_can_adopt_snapshot(self):
        workspace = await self.get('/api/meetings/resolve?kind=zoom_uuid&external_id=epochs')
        ws = workspace['workspace_id']
        async with connect(f'ws://127.0.0.1:{self.port}/workspaces/{ws}/events') as socket:
            current = await self.get('/api/meetings/resolve?kind=zoom_uuid&external_id=epochs&reset=1')
            reset = json.loads(await socket.recv())
            self.assertEqual(reset['generation'], current['generation'])
            for message in [
                {'type': 'utterance', 'text': 'old transcript'},
                {'type': 'task_update', 'task_id': 'old', 'status': 'completed', 'result': 'old result'},
                {'type': 'end_meeting'},
                {'type': 'cancel_task', 'task_id': 'old'},
            ]:
                await socket.send(json.dumps(message))
            # Same socket, ordered after the stale writes; only explicit adoption
            # of the new snapshot generation lets a browser write again.
            await socket.send(json.dumps({'type': 'utterance', 'text': 'new session',
                                          'generation': current['generation']}))
            event = json.loads(await asyncio.wait_for(socket.recv(), 1))
            self.assertEqual(event['type'], 'utterance')
            self.assertEqual(event['text'], 'new session')
        snapshot = self.store.snapshot(ws)
        self.assertEqual(len(snapshot['transcript']), 1)
        self.assertEqual(snapshot['tasks'], [])
        self.assertEqual(snapshot['artifacts'], [])
        self.assertEqual(snapshot['workspace']['status'], 'live')

    async def test_stale_resolve_to_connect_generation_is_rejected(self):
        from websockets.exceptions import ConnectionClosed
        workspace = await self.get('/api/meetings/resolve?kind=zoom_uuid&external_id=race')
        ws = workspace['workspace_id']
        await self.get('/api/meetings/resolve?kind=zoom_uuid&external_id=race&reset=1')
        with self.assertRaises(ConnectionClosed):
            async with connect(f'ws://127.0.0.1:{self.port}/workspaces/{ws}/events?generation=0') as socket:
                await socket.recv()

    async def test_old_live_client_disables_mirroring_after_reset(self):
        from sparkie.workspace_client import WorkspaceClient
        client = WorkspaceClient(f'127.0.0.1:{self.port}')
        received = []
        try:
            self.assertTrue(await client.open('zoom_uuid', 'client-reset'))
            client.on_message = received.append
            await self.get('/api/meetings/resolve?kind=zoom_uuid&external_id=client-reset&reset=1')
            async with asyncio.timeout(1):
                while client.enabled:
                    await asyncio.sleep(.001)
            await client.task_update({'task_id': 'old', 'status': 'completed', 'result': 'old'})
            await client.end_meeting()
            self.assertEqual(received, [])
            self.assertEqual(self.store.snapshot(client.workspace_id)['tasks'], [])
            self.assertEqual(self.store.get_workspace(client.workspace_id)['status'], 'live')
        finally:
            await client.close()

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
