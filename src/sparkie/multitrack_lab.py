"""Local synthetic meeting input; production participant demux/STT, never joins Zoom."""
import asyncio
import base64
from dataclasses import asdict
import json
import os
from pathlib import Path
import struct
import sys
import time
from uuid import uuid4

from dotenv import load_dotenv

from .participant_stt import ParticipantEars
from .providers import DeepgramEars
from .task_center import TranscriptLedger
from .zoom_audio import ZoomMacAudioMeeting


def validate_config(config):
    if not isinstance(config, dict) or config.get('action') != 'start':
        raise ValueError('invalid_config')
    if config.get('language') not in ('en', 'zh-CN'):
        raise ValueError('invalid_config')
    tracks = config.get('tracks')
    if not isinstance(tracks, list) or not 2 <= len(tracks) <= 4:
        raise ValueError('invalid_tracks')
    for track in tracks:
        if (not isinstance(track, dict) or not isinstance(track.get('name'), str)
                or not 1 <= len(track['name'].strip()) <= 80):
            raise ValueError('invalid_tracks')
    return config


class LabSession:
    def __init__(self, config, directory, emit, ears_factory=None):
        self.config = validate_config(config)
        self.directory = Path(directory)
        self.emit = emit
        self.ledger = TranscriptLedger(directory)
        self.meeting = ZoomMacAudioMeeting(self.directory, self.directory / 'no-native-binary')
        self.meeting.mixed_audio = True  # U frames use the production independent participant queue.
        users = [{'user_id': i + 1, 'name': t['name'], 'is_self': False}
                 for i, t in enumerate(config['tracks'])]
        self.meeting.handle_metadata(b'J', json.dumps(users).encode())
        self.frames = 0
        self.finished = False
        self.tasks = []
        self.track_samples = [0] * len(users)
        factory = ears_factory or (lambda: DeepgramEars(
            os.environ['DEEPGRAM_API_KEY'], self.directory.name, rate=32000,
            model=os.getenv('DEEPGRAM_MODEL') or 'nova-3', language=config['language']))
        self.ears = ParticipantEars(factory, speaker_name=self.meeting.speaker_name,
                                    is_self=self.meeting.is_self, max_streams=8,
                                    on_event=lambda kind, **fields: self.emit(kind, **fields))

    async def start(self):
        async def transcribe():
            async for event in self.ears.transcribe(self.meeting.participant_audio_stream()):
                self.ledger.append(event)
                self.emit('transcript', **asdict(event), mode='deepgram')
        self.tasks = [asyncio.create_task(transcribe())]
        self.emit('ready', mode='deepgram', tracks=self.config['tracks'])

    def accept(self, message):
        if (self.finished or type(message.get('sequence')) is not int
                or message['sequence'] != self.frames or self.frames >= 3000):
            raise ValueError('invalid_sequence_or_duration')
        packets = message.get('tracks')
        if not isinstance(packets, list) or len(packets) != len(self.track_samples):
            raise ValueError('invalid_tracks')
        decoded = []
        for value in packets:
            if not isinstance(value, str) or len(value) > 1710:
                raise ValueError('invalid_pcm')
            pcm = base64.b64decode(value, validate=True)
            if len(pcm) != 1280:
                raise ValueError('invalid_pcm')
            decoded.append(pcm)
        for task in self.tasks:
            if task.done():
                task.result()
                raise ValueError('consumer_closed')
        # Exercise the same U packet decoder and independent queues as the native bridge.
        for index, pcm in enumerate(decoded):
            payload = struct.pack('!IQ', index + 1, self.frames * 20) + pcm
            self.meeting.enqueue_frame(self.meeting.decode_audio(b'U', payload))
            self.track_samples[index] += 640
        self.frames += 1
        if self.frames % 25 == 0:
            self.emit('progress', timeline_ms=self.frames * 20,
                      track_samples=self.track_samples)

    async def finish(self):
        self.finished = True
        self.meeting.input_finished = True
        self.meeting.participant_input_done.set()
        await asyncio.wait_for(asyncio.gather(*self.tasks), 15)
        report = {'mode': 'deepgram', 'input': 'local_simulated_tracks',
                  'zoom_joined': False, 'realtime_model_called': False,
                  'timeline_ms': self.frames * 20,
                  'track_samples_32k': self.track_samples,
                  'transcript': sorted(self.ledger.records, key=lambda r: (r['timestamp_ms'], r['event_id']))}
        (self.directory / 'run.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        self.emit('completed', **report)
        return report

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.meeting.disable_participant_transcription()


async def main():
    load_dotenv()
    os.umask(0o077)
    reader = asyncio.StreamReader(limit=12000)
    pipe, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    session = None
    log = None
    def emit(kind, **fields):
        event = {'type': kind, **fields}
        line = json.dumps(event, ensure_ascii=False)
        print(line, flush=True)
        if log:
            log.write(line + '\n'); log.flush()
    try:
        config = validate_config(json.loads(await asyncio.wait_for(reader.readline(), 20)))
        if not os.getenv('DEEPGRAM_API_KEY'):
            emit('failed', reason='missing_deepgram_key'); return 1
        directory = Path('output/multitrack') / (time.strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:8])
        directory.mkdir(parents=True)
        log = (directory / 'events.jsonl').open('a')
        session = LabSession(config, directory, emit)
        await session.start()
        while True:
            line = await asyncio.wait_for(reader.readline(), 15)
            if not line:
                raise ValueError('input_disconnected')
            message = json.loads(line)
            if message.get('action') == 'finish':
                await session.finish(); return 0
            if message.get('action') != 'frame':
                raise ValueError('invalid_command')
            session.accept(message)
    except Exception as exc:
        # Provider exceptions and tool inputs may contain private data.
        emit('failed', reason='simulation_failed', error_type=type(exc).__name__)
        return 1
    finally:
        if session:
            await session.close()
        if log:
            log.close()
        pipe.close()


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
