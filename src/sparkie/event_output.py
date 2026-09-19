"""Bounded, asynchronous JSONL output, separate from durable event persistence.

Terminal diagnostics may be dropped under sustained backpressure; the event log
remains authoritative. Browser stdout carries audio/control and is lossless:
backpressure there fails explicitly instead of dropping protocol messages.
"""
import asyncio
from collections import deque
import contextlib
import io
import os

from .providers import ProviderError


class EventOutput:
    def __init__(self, stream, *, required=False, max_pending=1024 * 1024):
        self.stream, self.required, self.max_pending = stream, required, max_pending
        self.pending = deque()
        self.pending_bytes = 0
        self.dropped = 0
        self.failure = None
        self.fd = None
        self.was_blocking = None
        self.changed = asyncio.Event()
        self.closing = False
        self.task = None
        try:
            source_fd = stream.fileno()
        except (AttributeError, io.UnsupportedOperation):
            return  # StringIO in embedded clients/tests; no OS backpressure.
        self.was_blocking = os.get_blocking(source_fd)
        self.fd = os.dup(source_fd)
        os.set_blocking(self.fd, False)
        self.task = asyncio.create_task(self.pump())

    def publish(self, line):
        if self.failure:
            if self.required:
                raise ProviderError('event_output_disconnected') from None
            self.dropped += 1
            return
        if self.fd is None:
            try:
                self.stream.write(line + '\n')
                self.stream.flush()
            except (OSError, ValueError) as exc:
                self.failure = exc
                if self.required:
                    raise ProviderError('event_output_disconnected') from None
                self.dropped += 1
            return
        data = (line + '\n').encode('utf-8')
        if self.pending_bytes + len(data) > self.max_pending:
            if self.required:
                raise ProviderError('event_output_backpressure')
            self.dropped += 1
            return
        self.pending.append(data)
        self.pending_bytes += len(data)
        self.changed.set()

    async def writable(self):
        loop = asyncio.get_running_loop()
        ready = loop.create_future()
        def wake():
            if not ready.done():
                ready.set_result(None)
        loop.add_writer(self.fd, wake)
        try:
            await ready
        finally:
            loop.remove_writer(self.fd)

    async def pump(self):
        offset = 0
        try:
            while self.pending or not self.closing:
                self.changed.clear()
                if not self.pending:
                    await self.changed.wait()
                    continue
                data = self.pending[0]
                try:
                    count = os.write(self.fd, memoryview(data)[offset:])
                except BlockingIOError:
                    await self.writable()
                    continue
                except InterruptedError:
                    continue
                if not count:
                    raise BrokenPipeError('Output closed')
                offset += count
                self.pending_bytes -= count
                if offset == len(data):
                    self.pending.popleft()
                    offset = 0
                # Large/bursty task results must not starve conference PCM handling.
                await asyncio.sleep(0)
        except (OSError, ValueError) as exc:
            self.failure = exc
            self.dropped += len(self.pending)
            self.pending.clear()
            self.pending_bytes = 0

    async def close(self, timeout=1):
        self.closing = True
        self.changed.set()
        try:
            if self.task:
                try:
                    await asyncio.wait_for(self.task, timeout)
                except TimeoutError:
                    self.dropped += len(self.pending)
                finally:
                    self.task.cancel()
                    await asyncio.gather(self.task, return_exceptions=True)
        finally:
            if self.fd is not None:
                # dup shares O_NONBLOCK with the original tty/pipe: restore it.
                with contextlib.suppress(OSError):
                    os.set_blocking(self.fd, self.was_blocking)
                os.close(self.fd)
                self.fd = None
            self.pending.clear()
            self.pending_bytes = 0

    def diagnostics(self):
        return {'dropped_console_events': self.dropped,
                'output_error': type(self.failure).__name__ if self.failure else None}
