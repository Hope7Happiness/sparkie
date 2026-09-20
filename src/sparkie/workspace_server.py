"""Workspace HTTP + WebSocket server.

Routes (MVP, localhost):
  GET /api/meetings/resolve?kind=zoom_uuid&external_id=..&title=.. -> workspace
  GET /api/workspaces/<id>   -> full workspace snapshot
  GET /api/artifacts/<id>    -> single artifact incl. content
  GET /healthz               -> {"ok": true}
  WS  /workspaces/<id>/events -> broadcast stream; clients send
                               {"type": "utterance", "text": ..} to ingest

websockets' HTTP layer doesn't read request bodies, so all mutations go through
the event socket. One process, in-memory bus + SQLite store. Share links/auth are
intentionally out of scope for the MVP; bind stays on localhost by default.
"""
import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Response

from .agent_runtime import AgentRuntime, artifact_meta, utterance
from .event_bus import EventBus
from .task_center import CodexTaskWorker
from .workspace import WorkspaceStore

EVENTS_PATH = re.compile(r"^/workspaces/(ws_[0-9a-f]+)/events$")
WORKSPACE_PATH = re.compile(r"^/api/workspaces/(ws_[0-9a-f]+)$")
ARTIFACT_PATH = re.compile(r"^/api/artifacts/(art_[0-9a-f]+)$")

HEADERS = Headers({"Content-Type": "application/json",
                   "Access-Control-Allow-Origin": "*"})


def _respond(status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode()
    headers = Headers(HEADERS)
    headers["Content-Length"] = str(len(body))
    return Response(status, "OK" if status == 200 else "Error", headers, body)


class WorkspaceServer:
    def __init__(self, store, bus, runtime):
        self.store, self.bus, self.runtime = store, bus, runtime

    def process_request(self, connection, request):
        url = urlparse(request.path)
        path, query = url.path, parse_qs(url.query)
        if path == "/healthz":
            return _respond(200, {"ok": True})
        if path == "/api/workspaces":
            return _respond(200, {"workspaces": self.store.list_workspaces()})
        if path == "/api/meetings/resolve":
            kind = (query.get("kind") or [None])[0]
            external = (query.get("external_id") or [None])[0]
            if not kind or not external:
                return _respond(400, {"error": "kind and external_id required"})
            workspace_id = self.store.resolve_or_create(
                kind, external, (query.get("title") or [""])[0])
            if (query.get("reset") or [None])[0] == "1":
                self.runtime.reset_workspace(workspace_id)
            return _respond(200, self.store.get_workspace(workspace_id))
        match = WORKSPACE_PATH.match(path)
        if match:
            snapshot = self.store.snapshot(match.group(1))
            if snapshot is not None:
                snapshot['seq'] = self.bus.sequences.get(match.group(1), 0)
            return _respond(200 if snapshot else 404, snapshot or {"error": "unknown workspace"})
        match = ARTIFACT_PATH.match(path)
        if match:
            artifact = self.store.get_artifact(match.group(1))
            return _respond(200 if artifact else 404, artifact or {"error": "unknown artifact"})
        return None if EVENTS_PATH.match(path) else _respond(404, {"error": "not found"})

    async def handle(self, connection):
        url = urlparse(connection.request.path)
        match = EVENTS_PATH.match(url.path)
        if not match or not self.store.get_workspace(match.group(1)):
            await connection.close(4404, "unknown workspace")
            return
        workspace_id = match.group(1)
        generation = self.store.generation(workspace_id)
        requested = (parse_qs(url.query).get('generation') or [str(generation)])[0]
        if requested != str(generation):
            await connection.close(4409, 'workspace session changed')
            return
        queue = self.bus.subscribe(workspace_id)
        sender = asyncio.get_running_loop().create_task(self._send(connection, queue))
        try:
            async for raw in connection:
                try:
                    message = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                if not isinstance(message, dict):
                    continue
                if message.get('type') == 'artifact.control':
                    request_id = message.get('request_id')
                    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
                        continue
                    if message.get('generation', generation) != self.store.generation(workspace_id):
                        result = {'ok': False, 'error': 'workspace_session_changed'}
                    else:
                        result = self.runtime.artifact_control(
                            workspace_id, message.get('action'), message.get('artifact_id'))
                    await connection.send(json.dumps({'type': 'artifact.control.result',
                        'request_id': request_id, **result}))
                    continue
                # Old session sockets cannot write into a freshly reset canvas.
                # A browser may explicitly adopt the generation in its new snapshot.
                if message.get('generation', generation) != self.store.generation(workspace_id):
                    continue
                kind = message.get("type")
                if kind == "utterance" and isinstance(message.get("text"), str):
                    self.runtime.ingest(workspace_id, utterance(
                        workspace_id, message["text"][:4000], message.get("speaker"),
                        source=message.get("source") if message.get("source") == "bot" else "human",
                        is_final=message.get("is_final", True)),
                        live_mirror=bool(message.get("live")))
                elif kind == "end_meeting":
                    self.runtime.end_meeting(workspace_id, live_mirror=bool(message.get('live')))
                elif kind == "cancel_task" and isinstance(message.get("task_id"), str):
                    self.runtime.cancel_task(workspace_id, message["task_id"])
                elif kind == "task_update":
                    self.runtime.mirror_task(workspace_id, message)
        finally:
            sender.cancel()
            self.bus.unsubscribe(workspace_id, queue)

    async def _send(self, connection, queue):
        try:
            while True:
                await connection.send(json.dumps(await queue.get(), ensure_ascii=False))
        except asyncio.CancelledError:
            pass


async def serve_workspace(store, bus, runtime, host="127.0.0.1", port=8790):
    app = WorkspaceServer(store, bus, runtime)
    server = await serve(app.handle, host, port, process_request=app.process_request)
    return server


async def workspace_session(args):
    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = WorkspaceStore(args.db)
    bus = EventBus()
    worker = None
    if args.worker in ("codex", "devin"):
        if args.worker == "devin":
            from .devin_acp import DevinTaskWorker
            worker = DevinTaskWorker(model=os.getenv("DEVIN_MODEL") or "swe-1-6-fast")
        else:
            worker = CodexTaskWorker(model=os.getenv("SPARKIE_CODEX_MODEL") or "gpt-5.6-terra",
                                     workspace=Path.cwd())
        async def task_worker(instruction, transcript):
            from .task_artifacts import materialize_result
            prompt = (instruction + "\n\nFor a file deliverable, use the sparkie-artifact "
                      "declaration. Otherwise reply with the complete deliverable itself "
                      "in Markdown, not just a description of it or a file path.")
            answer = await worker.run(prompt, transcript)
            output = await asyncio.to_thread(materialize_result, answer, worker.workspace)
            if output.get('artifact_error'):
                raise ValueError(output['artifact_error'])
            content = output.get('artifact', {}).get('content', {'markdown': output['result']})
            title, summary = artifact_meta(content['markdown'])
            return {"type": "report", "title": title,
                    "summary": summary, "content": content}
    else:
        async def task_worker(instruction, transcript):
            return {"type": "demo", "title": instruction[:80],
                    "summary": "Simulated worker — no research was performed.",
                    "content": {"instruction": instruction,
                                "transcript_records": len(transcript)}}
    runtime = AgentRuntime(store, bus, task_worker)
    server = await serve_workspace(store, bus, runtime, args.host, args.port)
    print(f"Workspace server on http://{args.host}:{args.port} "
          f"(db: {args.db}, worker: {args.worker})", flush=True)
    try:
        await server.serve_forever()
    finally:
        try:
            await runtime.close()
        finally:
            try:
                if worker is not None and hasattr(worker, 'close'):
                    await worker.close()
            finally:
                store.close()
