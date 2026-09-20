"""Synthetic native packets through the production Zoom Realtime session routing."""
import asyncio
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sparkie import realtime_session
from sparkie.contracts import TranscriptEvent
from sparkie.zoom_audio import ZoomMacAudioMeeting
from sparkie.providers import ProviderError
from test_zoom_audio import packet


class RealtimeParticipantSessionTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, provider_failure=False):
        sessions, received, snapshots = [], [], []
        class Meeting(ZoomMacAudioMeeting):
            async def join(self):
                self.reader = asyncio.StreamReader()
                self.reader_task = asyncio.create_task(self.receive())
                self.handle_metadata(b'J', json.dumps([
                    {'user_id': 10, 'name': 'Same name', 'is_self': False},
                    {'user_id': 20, 'name': 'Same name', 'is_self': False}]).encode())
                self.reader.feed_data(
                    packet(b'U', struct.pack('!IQ', 10, 1000) + struct.pack('<h', 100) * 640) +
                    packet(b'U', struct.pack('!IQ', 20, 1000) + struct.pack('<h', 200) * 640) +
                    packet(b'A', struct.pack('<h', 300) * 320) * 100)
            async def audio(self):
                for _ in range(100):
                    yield await asyncio.wait_for(self.queue.get(), 2)
            async def stop_speaking(self): pass
        class Agent:
            def __init__(self, key, audio, center, *a, **kw):
                self.ready = asyncio.Event(); self.model = 'fake'; self.last_speech_end = None
                snapshots.append(center.ledger)
            async def run(self): self.ready.set(); await asyncio.Event().wait()
            async def notify_tasks(self): await asyncio.Event().wait()
            async def append(self, frame): received.append(frame)
        class Ears:
            def __init__(self, *a, **kw):
                self.rate = kw['rate']; self.model = kw['model']; self.language = kw['language']
            async def transcribe(self, frames):
                self.on_ready()
                if provider_failure: raise ProviderError('synthetic STT failure')
                packets = []
                sessions.append((self.rate, packets))
                async for frame in frames: packets.append(frame.pcm)
                value = struct.unpack('<h', packets[0][:2])[0]
                yield TranscriptEvent('test', 'dg-1', 20, f'words from {value}')
        class Worker:
            backend, model = 'fake', 'fake'
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(transport='zoom', output=Path(directory), seconds=10, language='en')
            read_fd, write_fd = os.pipe(); os.close(write_fd)
            stream = os.fdopen(read_fd)
            previous = os.umask(0o077)
            try:
                with patch.dict(os.environ, {'OPENAI_API_KEY':'fake', 'DEEPGRAM_API_KEY':'fake', 'ZOOM_PLATFORM':'macos'}), \
                     patch('sparkie.zoom_audio.ZoomMacAudioMeeting', Meeting), \
                     patch.object(realtime_session, 'RealtimeAgent', Agent), \
                     patch.object(realtime_session, 'DeepgramEars', Ears), \
                     patch.object(realtime_session, 'configured_task_worker', return_value=Worker()), \
                     patch('sys.stdin', stream), redirect_stdout(io.StringIO()):
                    result = await realtime_session.run(args)
            finally:
                os.umask(previous); stream.close()
            root = next(Path(directory).iterdir())
            events = [json.loads(x) for x in (root/'events.jsonl').read_text().splitlines()]
            report = json.loads((root/'run.json').read_text())
        self.assertEqual(result, 0)
        self.assertEqual(sum(len(f.pcm) for f in received), 48000)  # One second, not one per speaker.
        self.assertTrue(all(f.sample_rate == 24000 and f.speaker_id is None for f in received))
        config = next(e for e in events if e['type']=='transcription_config')
        self.assertEqual(config['input_mode'], 'per_participant')
        self.assertEqual(config['sample_rate'], 32000)
        if provider_failure:
            self.assertTrue(any(e['type']=='transcript_degraded' for e in events))
            self.assertTrue(any(r.get('reason')=='deepgram_unavailable' for r in snapshots[0].records))
        else:
            self.assertEqual(len(sessions), 2)
            self.assertEqual({rate for rate, _ in sessions}, {32000})
            records = report['transcript']
            self.assertEqual({r['speaker_id'] for r in records}, {'zoom:10','zoom:20'})
            self.assertEqual({r['timestamp_ms'] for r in records}, {1020})
            self.assertEqual({r['speaker'] for r in records}, {'Same name'})
            self.assertEqual({r['text'] for r in records}, {'words from 100','words from 200'})
            self.assertEqual({r['speaker_id'] for r in snapshots[0].snapshot()}, {'zoom:10','zoom:20'})
            self.assertFalse(any(r.get('reason')=='zoom_echo_gate' for r in snapshots[0].records))

    async def test_default_zoom_realtime_persists_separate_speakers_and_single_foreground_clock(self):
        await self.exercise()

    async def test_stt_failure_preserves_foreground_and_records_coverage_gap(self):
        await self.exercise(provider_failure=True)
