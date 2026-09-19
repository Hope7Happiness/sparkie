import asyncio
import json
import signal
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sparkie.contracts import TranscriptEvent
from sparkie.local_session import local_session


class LocalSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_signal_cancels_reasoning_and_saves_report(self):
        started, cancelled = asyncio.Event(), asyncio.Event()
        class Brain:
            model = 'test-model'
            async def answer(self, snapshot):
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
        class Ears:
            async def transcribe(self, frames):
                yield TranscriptEvent('m', '1', 0, 'Sparkie, what is a WebSocket?')
                await asyncio.Event().wait()
        meeting = SimpleNamespace(join=AsyncMock(), play_audio=AsyncMock(), leave=AsyncMock(),
                                  stop_speaking=AsyncMock(), request_stop=lambda: None,
                                  audio=lambda: None, diagnostics=lambda: {})
        loop = asyncio.get_running_loop()
        handlers = {}
        with tempfile.TemporaryDirectory() as path, \
             patch.dict('os.environ', {'DEEPGRAM_API_KEY': 'test'}), \
             patch('sparkie.local_session.configured_brain', return_value=Brain()), \
             patch('sparkie.local_session.LocalAudioMeeting', return_value=meeting), \
             patch('sparkie.local_session.DeepgramEars', return_value=Ears()), \
             patch('sparkie.local_session.DeepgramMouth', return_value=SimpleNamespace(synthesize=AsyncMock(return_value=b'ack'))), \
             patch.object(loop, 'add_signal_handler', side_effect=lambda sig, callback: handlers.update({sig: callback})), \
             patch.object(loop, 'remove_signal_handler'), patch('sparkie.local_session.signal.signal'), patch('builtins.print'):
            args = SimpleNamespace(language='en', response_mode='qa', input_device=None, output_device=None,
                                   echo_mode='speaker', seconds=60, output=Path(path))
            task = asyncio.create_task(local_session(args))
            await asyncio.wait_for(started.wait(), 1)
            handlers[signal.SIGTERM]()
            self.assertEqual(await asyncio.wait_for(task, 1), 0)
            self.assertTrue(cancelled.is_set())
            report = json.loads(next(Path(path).glob('*/run.json')).read_text())
            self.assertEqual(report['exit_reason'], 'stopped')
            self.assertTrue(any(e['type'] == 'response_cancelled' for e in report['events']))
            meeting.leave.assert_awaited()
