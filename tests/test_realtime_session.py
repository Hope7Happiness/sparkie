import asyncio
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sparkie.audio import AudioFrame
from sparkie import realtime_session


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_deepgram_failure_does_not_prevent_realtime_audio_and_gap_is_persisted(self):
        class Audio:
            captured_samples = 0
            audio_origin = None
            timing_reliable = True
            _gate_until = 0
            joined = False
            closed = False
            def __init__(self, *args, **kwargs): self.echo_mode = kwargs['echo_mode']
            async def join(self): Audio.joined = True
            async def audio(self):
                self.captured_samples = 240
                yield AudioFrame(0, bytes(480), 24000)
            def request_stop(self): pass
            async def leave(self): Audio.closed = True
            def diagnostics(self): return {}
        class Agent:
            received = []
            def __init__(self, *args, **kwargs):
                self.ready = asyncio.Event(); self.model = 'test'; self.last_speech_end = None
            async def run(self): self.ready.set(); await asyncio.Event().wait()
            async def append(self, frame): Agent.received.append(frame)
        class Ears:
            def __init__(self, *args, **kwargs): pass
            async def transcribe(self, frames):
                raise RuntimeError('test network failure')
                yield
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(output=Path(directory), input_device=None, output_device=None,
                                   echo_mode='headphones', seconds=10, language='en')
            read_fd, write_fd = os.pipe()
            os.close(write_fd)
            stream = os.fdopen(read_fd)
            old_umask = os.umask(0o077)
            try:
                with patch.dict(os.environ, {'OPENAI_API_KEY': 'fake', 'DEEPGRAM_API_KEY': 'fake'}), \
                     patch.object(realtime_session, 'RealtimeLocalAudio', Audio), \
                     patch.object(realtime_session, 'RealtimeAgent', Agent), \
                     patch.object(realtime_session, 'DeepgramEars', Ears), \
                     patch('sys.stdin', stream), redirect_stdout(io.StringIO()):
                    result = await realtime_session.run(args)
            finally:
                os.umask(old_umask)
                stream.close()
            self.assertEqual(result, 0)
            self.assertTrue(Audio.joined and Audio.closed)
            self.assertEqual(len(Agent.received), 1)
            session = next(Path(directory).iterdir())
            records = [json.loads(line) for line in (session / 'transcript.jsonl').read_text().splitlines()]
            self.assertEqual(records[0]['reason'], 'deepgram_unavailable')
            self.assertEqual(json.loads((session / 'run.json').read_text())['exit_reason'], 'completed')
