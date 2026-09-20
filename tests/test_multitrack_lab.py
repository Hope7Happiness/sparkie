import asyncio
import base64
import json
from pathlib import Path
import struct
import tempfile
import unittest

from sparkie.contracts import TranscriptEvent
from sparkie.multitrack_lab import LabSession, validate_config
from sparkie.providers import ProviderError


def packet(sequence, values):
    return {'action': 'frame', 'sequence': sequence, 'tracks': [
        base64.b64encode(struct.pack('<h', value) * 640).decode() for value in values]}


class MultitrackTests(unittest.IsolatedAsyncioTestCase):
    async def test_overlapping_same_name_tracks_stay_separate_and_silence_does_not_connect(self):
        seen = []
        class Ears:
            async def transcribe(self, frames):
                self.on_ready()
                samples = []
                async for frame in frames:
                    samples.extend(struct.unpack('<' + 'h' * (len(frame.pcm) // 2), frame.pcm))
                values = set(samples) - {0}
                seen.append(values)
                yield TranscriptEvent('test', 'dg-1', 40, str(sorted(values)))
        with tempfile.TemporaryDirectory() as directory:
            session = LabSession({'action': 'start', 'language': 'en',
                                  'tracks': [{'name': 'Same'}, {'name': 'Same'}, {'name': 'Silent'}]},
                                 directory, lambda *a, **k: None, ears_factory=Ears)
            await session.start()
            try:
                for sequence in range(5):
                    session.accept(packet(sequence, [100, 200, 0])); await asyncio.sleep(0)
                report = await session.finish()
                self.assertEqual({frozenset(v) for v in seen}, {frozenset({100}), frozenset({200})})
                self.assertEqual({r['speaker_id'] for r in report['transcript']}, {'zoom:1', 'zoom:2'})
                self.assertEqual({r['speaker'] for r in report['transcript']}, {'Same'})
                self.assertEqual(report['timeline_ms'], 100)
                self.assertFalse(report['zoom_joined'])
                self.assertFalse(report['realtime_model_called'])
                self.assertEqual(json.loads((Path(directory) / 'run.json').read_text()), report)
            finally:
                await session.close()

    async def test_invalid_frames_do_not_partially_enter_a_track(self):
        with tempfile.TemporaryDirectory() as directory:
            session = LabSession({'action': 'start', 'language': 'en', 'tracks': [{'name':'A'}, {'name':'B'}]},
                                 directory, lambda *a, **k: None, ears_factory=lambda: None)
            for message in (packet(1, [100, 200]), packet(0, [100]),
                            {'sequence': 0, 'tracks': [packet(0, [100])['tracks'][0], 'bad-pcm']}):
                with self.assertRaises(ValueError): session.accept(message)
                self.assertEqual(session.frames, 0)
                self.assertTrue(session.meeting.participant_queue.empty())
            await session.close()

    async def test_provider_failure_is_not_reported_as_success_and_closes_stream(self):
        closed = asyncio.Event()
        class Ears:
            async def transcribe(self, frames):
                try:
                    raise ProviderError('private provider detail')
                    yield
                finally:
                    closed.set()
        with tempfile.TemporaryDirectory() as directory:
            events = []
            session = LabSession({'action': 'start', 'language': 'en', 'tracks': [{'name':'A'}, {'name':'B'}]},
                                 directory, lambda kind, **fields: events.append(kind), ears_factory=Ears)
            await session.start()
            try:
                session.accept(packet(0, [100, 200]))
                with self.assertRaises(ProviderError): await session.finish()
                self.assertNotIn('completed', events)
                self.assertFalse((Path(directory) / 'run.json').exists())
                self.assertTrue(closed.is_set())
            finally:
                await session.close()
            self.assertTrue(all(task.done() for task in session.tasks))

    def test_bounds_and_language_are_validated(self):
        for config in ({}, {'action':'start','language':'en','tracks':[{'name':'A'}]},
                       {'action':'start','language':'invalid','tracks':[{'name':'A'},{'name':'B'}]},
                       {'action':'start','language':'en','tracks':[{'name':'A'},{'name':''}]}):
            with self.assertRaises(ValueError): validate_config(config)
