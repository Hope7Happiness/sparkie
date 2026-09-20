"""Workspace-scoped in-memory event bus.

One meeting workspace broadcasts the same event stream to every connected client —
the Zoom panel and a browser workspace are just two subscribers. Persistence lives
in WorkspaceStore; this is the realtime fan-out layer.
"""
import asyncio


class EventBus:
    def __init__(self, queue_limit=256):
        self.queue_limit = queue_limit
        self.subscribers = {}
        self.sequences = {}

    def subscribe(self, workspace_id):
        queue = asyncio.Queue(maxsize=self.queue_limit)
        self.subscribers.setdefault(workspace_id, set()).add(queue)
        return queue

    def unsubscribe(self, workspace_id, queue):
        subscribers = self.subscribers.get(workspace_id)
        if subscribers:
            subscribers.discard(queue)
            if not subscribers:
                del self.subscribers[workspace_id]

    def publish(self, workspace_id, event):
        event = {"workspace_id": workspace_id,
                 "seq": self.sequences.get(workspace_id, 0) + 1, **event}
        self.sequences[workspace_id] = event["seq"]
        for queue in list(self.subscribers.get(workspace_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A client that cannot keep up loses its subscription rather than
                # silently missing events or blocking the meeting loop.
                self.unsubscribe(workspace_id, queue)
        return event

    def subscriber_count(self, workspace_id):
        return len(self.subscribers.get(workspace_id, ()))
