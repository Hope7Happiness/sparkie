"""Best-effort client that mirrors a live meeting session into a workspace.

The meeting never depends on the workspace server: every failure disables the
client silently so Zoom audio / realtime keep running without it.
"""
import asyncio
import json

import httpx
from websockets.asyncio.client import connect


class WorkspaceClient:
    def __init__(self, server="127.0.0.1:8790", timeout=2.0):
        self.server, self.timeout = server, timeout
        self.socket = None
        self.workspace_id = None
        self.enabled = True
        self.on_message = None
        self._drain = None

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
            self.socket = await connect(
                f"ws://{self.server}/workspaces/{self.workspace_id}/events",
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
                if self.on_message is None:
                    continue
                try:
                    self.on_message(json.loads(raw))
                except Exception:
                    pass
        except Exception:
            pass

    async def send(self, message):
        if not self.enabled or self.socket is None:
            return
        try:
            await self.socket.send(json.dumps(message))
        except Exception:
            self.enabled = False

    async def utterance(self, text, speaker=None, source="human", is_final=True):
        await self.send({"type": "utterance", "text": text, "speaker": speaker,
                         "source": source, "is_final": is_final, "live": True})

    async def task_update(self, fields):
        await self.send({"type": "task_update", **fields})

    async def end_meeting(self):
        await self.send({"type": "end_meeting"})
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
