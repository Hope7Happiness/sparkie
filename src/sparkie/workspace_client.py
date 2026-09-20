"""Best-effort client that mirrors a live meeting session into a workspace.

The meeting never depends on the workspace server: every failure disables the
mirroring silently so Zoom audio / realtime keep running without it.
Explicit artifact controls return acknowledged results or bounded errors.
"""
import asyncio
import json
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect


class WorkspaceClient:
    def __init__(self, server="127.0.0.1:8790", timeout=2.0):
        self.server, self.timeout = server, timeout
        self.socket = None
        self.workspace_id = None
        self.generation = None
        self.enabled = True
        self.on_message = None
        self._drain = None
        self._requests = {}

    async def open(self, kind, external_id, title="", reset=False):
        try:
            params = {"kind": kind, "external_id": external_id, "title": title}
            if reset:
                params["reset"] = "1"
            async with httpx.AsyncClient(timeout=self.timeout) as http:
                response = await http.get(f"http://{self.server}/api/meetings/resolve",
                                          params=params)
                response.raise_for_status()
            self.workspace_id = response.json()["workspace_id"]
            self.generation = response.json()['generation']
            self.socket = await connect(
                f"ws://{self.server}/workspaces/{self.workspace_id}/events?generation={self.generation}",
                open_timeout=self.timeout, close_timeout=1)
            # Broadcasts (e.g. a browser cancel) are delivered to the optional
            # on_message hook; draining also keeps the socket from stalling.
            self._drain = asyncio.get_running_loop().create_task(self._listen())
        except Exception:
            self.enabled = False
        return self.enabled

    async def _listen(self):
        try:
            async for raw in self.socket:
                message = json.loads(raw)
                if message.get('type') == 'artifact.control.result':
                    pending = self._requests.get(message.get('request_id'))
                    if pending is not None and not pending.done():
                        pending.set_result({k: v for k, v in message.items()
                                            if k not in ('type', 'request_id')})
                    continue
                if message.get('type') == 'workspace.reset' and message.get('generation') != self.generation:
                    self.enabled = False
                    return
                if self.on_message is None:
                    continue
                try:
                    self.on_message(message)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            self.enabled = False
            for pending in list(self._requests.values()):
                if not pending.done():
                    pending.set_result({'ok': False, 'error': 'workspace_unavailable'})

    async def artifact_control(self, action, artifact_id=None):
        if not self.enabled or self.socket is None:
            return {'ok': False, 'error': 'workspace_unavailable'}
        if len(self._requests) >= 32:
            return {'ok': False, 'error': 'workspace_busy'}
        request_id = uuid4().hex
        pending = asyncio.get_running_loop().create_future()
        self._requests[request_id] = pending
        try:
            async with asyncio.timeout(self.timeout):
                await self.socket.send(json.dumps({'type': 'artifact.control',
                    'request_id': request_id, 'generation': self.generation,
                    'action': action, 'artifact_id': artifact_id}))
                return await pending
        except TimeoutError:
            return {'ok': False, 'error': 'workspace_timeout', 'outcome': 'unknown'}
        except Exception:
            return {'ok': False, 'error': 'workspace_unavailable'}
        finally:
            self._requests.pop(request_id, None)

    async def send(self, message):
        if not self.enabled or self.socket is None:
            return
        try:
            await self.socket.send(json.dumps({**message, 'generation': self.generation}))
        except Exception:
            self.enabled = False

    async def utterance(self, text, speaker=None, source="human", is_final=True):
        await self.send({"type": "utterance", "text": text, "speaker": speaker,
                         "source": source, "is_final": is_final, "live": True})

    async def task_update(self, fields):
        await self.send({"type": "task_update", **fields})

    async def end_meeting(self):
        await self.send({"type": "end_meeting", "live": True})
        # Give the report task a moment to be queued before the socket closes.
        if self.enabled:
            await asyncio.sleep(.3)

    async def close(self):
        if self._drain:
            self._drain.cancel()
            await asyncio.gather(self._drain, return_exceptions=True)
        if self.socket is not None:
            try:
                await self.socket.close()
            except Exception:
                pass
