import asyncio
import contextlib
import json
import os
from pathlib import Path
import pty
import struct
import tempfile
import unittest

from sparkie.event_output import EventOutput
from sparkie.providers import ProviderError
from sparkie.zoom_audio import ZoomAudioMeeting


def packet(kind, data):
    return kind + struct.pack('!I', len(data)) + data


class EventOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_terminal_does_not_break_zoom_playback_ack_or_pcm(self):
        master, slave = pty.openpty()
        os.set_blocking(slave, False)
        # Reproduce the user's terminal backpressure before emitting SDK playback events.
        while True:
            try:
                os.write(slave, b'x' * 4096)
            except BlockingIOError:
                break
        stream = os.fdopen(os.dup(slave), 'wb', buffering=0)
        output = EventOutput(stream)
        with tempfile.TemporaryDirectory() as directory:
            meeting = ZoomAudioMeeting(directory)
            meeting.reader = asyncio.StreamReader()
            logfile = Path(directory) / 'events.jsonl'
            def emit(kind, **fields):
                line = json.dumps({'type': kind, **fields})
                with logfile.open('a') as log:
                    log.write(line + '\n')
                output.publish(line)
            meeting.on_event = emit
            future = asyncio.get_running_loop().create_future()
            meeting.playbacks[335] = future
            meeting.reader_task = asyncio.create_task(meeting.receive())
            try:
                # A large completed task was logged immediately before the failure.
                emit('background_task', result='result ' * 20000)
                meeting.reader.feed_data(packet(b'S', struct.pack('!I', 335)) +
                                         packet(b'D', struct.pack('!I', 335)) +
                                         packet(b'A', bytes(640)))
                await asyncio.wait_for(future, .5)
                frame = await asyncio.wait_for(meeting.queue.get(), .5)
                self.assertEqual(len(frame.pcm), 640)
                self.assertIsNone(meeting.failure)
                self.assertFalse(meeting.stopped.is_set())
                records = [json.loads(line) for line in logfile.read_text().splitlines()]
                self.assertEqual([r['type'] for r in records], ['background_task', 'zoom_playback_submitted'])
                self.assertGreater(output.pending_bytes, 0)
            finally:
                await meeting.leave()
                await output.close(timeout=.02)
                stream.close()
                os.close(slave)
                os.close(master)

    async def test_partial_pipe_writes_resume_with_complete_ordered_json(self):
        reader, writer = os.pipe()
        stream = os.fdopen(os.dup(writer), 'wb', buffering=0)
        output = EventOutput(stream, required=True)
        expected = [json.dumps({'seq': i, 'text': '中文' * 1000}) for i in range(60)]
        try:
            for line in expected:
                output.publish(line)
            await asyncio.sleep(.02)
            self.assertGreater(output.pending_bytes, 0)
            os.set_blocking(reader, False)
            received = bytearray()
            async with asyncio.timeout(3):
                while output.pending_bytes:
                    with contextlib.suppress(BlockingIOError):
                        received.extend(os.read(reader, 131072))
                    await asyncio.sleep(.001)
                while True:
                    try:
                        received.extend(os.read(reader, 131072))
                    except BlockingIOError:
                        break
            self.assertEqual(received.decode().splitlines(), expected)
            self.assertEqual(output.dropped, 0)
        finally:
            await output.close()
            self.assertTrue(os.get_blocking(writer))
            stream.close()
            os.close(writer)
            os.close(reader)

    async def test_bounded_diagnostics_but_browser_protocol_never_silently_drops(self):
        for required in (False, True):
            reader, writer = os.pipe()
            stream = os.fdopen(os.dup(writer), 'wb', buffering=0)
            output = EventOutput(stream, required=required, max_pending=8)
            try:
                if required:
                    with self.assertRaisesRegex(ProviderError, 'backpressure'):
                        output.publish('too big for the queue')
                else:
                    output.publish('too big for the queue')
                    self.assertEqual(output.dropped, 1)
                self.assertEqual(output.pending_bytes, 0)
            finally:
                await output.close()
                stream.close()
                os.close(writer)
                os.close(reader)

    async def test_broken_console_does_not_raise_into_audio_callback(self):
        reader, writer = os.pipe()
        stream = os.fdopen(os.dup(writer), 'wb', buffering=0)
        os.close(reader)
        output = EventOutput(stream)
        try:
            output.publish('{}')
            await asyncio.sleep(.01)
            self.assertIsInstance(output.failure, BrokenPipeError)
            output.publish('{}')
            self.assertEqual(output.dropped, 2)
        finally:
            await output.close()
            stream.close()
            os.close(writer)

    async def test_failing_error_sink_still_resolves_playback_and_stops_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            meeting = ZoomAudioMeeting(directory)
            meeting.reader = asyncio.StreamReader()
            def failed_sink(*args, **kwargs):
                raise BlockingIOError('terminal full')
            meeting.on_event = failed_sink
            pending = asyncio.get_running_loop().create_future()
            meeting.playbacks[1] = pending
            meeting.reader.feed_data(packet(b'S', struct.pack('!I', 1)))
            try:
                with self.assertRaises(BlockingIOError):
                    await meeting.receive()
                self.assertTrue(meeting.stopped.is_set())
                with self.assertRaises(BlockingIOError):
                    await asyncio.wait_for(pending, .1)
            finally:
                await meeting.leave()
