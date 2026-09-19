"""Real Zoom PCM adapter; Docker contains only the SDK, never provider credentials."""
import asyncio
import contextlib
from pathlib import Path
import secrets
import struct
import time

from .audio import AudioFrame
from .zoom_config import meeting_config, private_write


class ZoomAudioMeeting:
    def __init__(self, runtime, *, max_seconds=300, join_timeout=120):
        self.runtime = Path(runtime).resolve()
        self.max_seconds, self.join_timeout = max_seconds, join_timeout
        self.name = 'sparkie-zoom-voice-' + secrets.token_hex(4)
        self.reader = self.writer = self.reader_task = None
        self.queue = asyncio.Queue(maxsize=1000)  # Bounded 10s cushion for startup/network stalls.
        self._backlogged = False
        self.mic_ready = asyncio.Event()
        self.audio_ready = asyncio.Event()
        self.stopped = asyncio.Event()
        self.on_event = lambda *a, **kw: None
        self.failure = None
        self.playbacks = {}
        self.play_id = 0
        self.frames_received = self.bytes_received = 0
        self.audio_origin = None  # Network input does not establish a remote acoustic clock.
        self.last_playback_started_at = None  # SDK acceptance is not a DAC timestamp.
        self._owns_container = False
        self._write_lock = asyncio.Lock()

    async def docker(self, *args):
        process = await asyncio.create_subprocess_exec('docker', *args, stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.PIPE)
        try:
            out, _ = await asyncio.wait_for(process.communicate(), 20)
        except BaseException:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise RuntimeError('Docker command failed: ' + args[0])
        return out.decode().strip()

    async def join(self):
        config = meeting_config()
        values = {k: config[k] for k in ('meeting_number', 'token', 'meeting_password')}
        values.update(recording_token='', onBehalfOf_Token='', GetVideoRawData='false',
                      GetAudioRawData='true', SendVideoRawData='false', SendAudioRawData='true')
        if any(any(c in v for c in '\n\r"') for v in values.values()):
            raise ValueError('Zoom configuration contains unsupported characters')
        self.runtime.mkdir(parents=True, exist_ok=True)
        token = secrets.token_hex(32)
        private_write(self.runtime / 'bridge-token', token)
        private_write(self.runtime / 'config.txt', ''.join(f'{k}: "{v}"\n' for k, v in values.items()))
        # Claim the unique name before starting so cancellation can still clean up.
        self._owns_container = True
        await self.docker('run', '-d', '--name', self.name, '--platform', 'linux/arm64',
                          '-p', '127.0.0.1::8769',
                          '-v', f'{self.runtime / "bridge-token"}:/run/bridge-token:ro',
                          '-v', f'{self.runtime / "config.txt"}:/run/config.txt:ro',
                          'sparkie-zoom-voice:7.0.5', '/bin/bash', '-lc',
                          'cp /run/config.txt /app/demo/bin/config.txt; '
                          'bash /app/demo/setup-pulseaudio.sh >/tmp/audio-setup.log 2>&1; '
                          'exec /app/demo/bin/meetingSDKDemo')
        port = int((await self.docker('port', self.name, '8769/tcp')).rsplit(':', 1)[1])
        self.on_event('zoom_connecting', container=self.name,
                      hint='Host must admit Sparkie and allow recording for audio access.')
        async with asyncio.timeout(self.join_timeout):
            while True:
                try:
                    self.reader, self.writer = await asyncio.open_connection('127.0.0.1', port)
                    self.writer.write(token.encode())
                    await self.writer.drain()
                    # Docker can accept TCP before the native bridge starts listening.
                    kind, payload = await self.read_packet()
                    if kind != b'H' or payload:
                        raise RuntimeError('Invalid Zoom bridge handshake')
                    break
                except (OSError, asyncio.IncompleteReadError):
                    if self.writer:
                        self.writer.close()
                        await self.writer.wait_closed()
                    await asyncio.sleep(.5)
            self.reader_task = asyncio.create_task(self.receive())
            while not (self.audio_ready.is_set() and self.mic_ready.is_set()):
                if self.failure:
                    raise self.failure
                await asyncio.sleep(.05)
        self.on_event('zoom_audio_ready', sample_rate=32000, channels=1)

    async def read_packet(self):
        header = await self.reader.readexactly(5)
        size = struct.unpack('!I', header[1:])[0]
        if size > 64000:
            raise RuntimeError('Invalid Zoom bridge packet size')
        return header[:1], await self.reader.readexactly(size)

    async def receive(self):
        try:
            while True:
                kind, data = await asyncio.wait_for(self.read_packet(), 10 if self.audio_ready.is_set() else self.join_timeout)
                if kind == b'A':
                    if not data or len(data) % 2:
                        raise RuntimeError('Invalid Zoom PCM frame')
                    self.frames_received += 1
                    self.bytes_received += len(data)
                    self.audio_ready.set()
                    if self.queue.qsize() >= 250 and not self._backlogged:
                        self._backlogged = True
                        self.on_event("audio_warning", reason="zoom_input_backlog", queued_frames=self.queue.qsize())
                    self.queue.put_nowait(AudioFrame(self.frames_received, data))
                    if self.frames_received % 50 == 0:
                        self.on_event('zoom_audio', frames=self.frames_received,
                                      peak=max(abs(v[0]) for v in struct.iter_unpack('<h', data)))
                elif kind == b'M':
                    self.mic_ready.set()
                    self.on_event('zoom_microphone_ready')
                elif kind == b'N':
                    self.mic_ready.clear()
                    self.on_event('zoom_microphone_muted')
                    for future in self.playbacks.values():
                        if not future.done():
                            future.set_exception(RuntimeError('Zoom microphone was muted during playback'))
                elif kind in {b'S', b'D'} and len(data) == 4:
                    ident = struct.unpack('!I', data)[0]
                    entry = self.playbacks.get(ident)
                    if entry:
                        if kind == b'S':
                            self.on_event('zoom_playback_submitted', playback_id=ident,
                                          note='SDK accepted first frame; remote audible latency is not measured.')
                        elif not entry.done():
                            entry.set_result(None)
                elif kind == b'E':
                    # Only fixed native error messages; never forward arbitrary provider bodies.
                    raise RuntimeError('Zoom bridge rejected audio; inspect container state')
                else:
                    raise RuntimeError('Invalid Zoom bridge event')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.failure = exc
            self.on_event('audio_failed', reason=type(exc).__name__)
            for future in self.playbacks.values():
                if not future.done():
                    future.set_exception(exc)
            self.stopped.set()

    async def audio(self):
        started = time.monotonic()
        while not self.stopped.is_set() and time.monotonic() - started < self.max_seconds:
            try:
                frame = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                await asyncio.sleep(.01)
                continue
            if self._backlogged and self.queue.qsize() < 50:
                self._backlogged = False
                self.on_event("zoom_input_recovered")
            yield frame
        if self.failure:
            raise self.failure

    async def send_packet(self, kind, data=b''):
        if self.failure:
            raise self.failure
        async with self._write_lock:
            self.writer.write(kind + struct.pack('!I', len(data)) + data)
            await self.writer.drain()

    async def play_audio(self, pcm, sample_rate):
        if sample_rate != 32000 or not pcm or len(pcm) % 2 or len(pcm) > 1920000:
            raise ValueError('Zoom output must be mono PCM16 32000 Hz, at most 30 seconds')
        if not self.mic_ready.is_set():
            raise RuntimeError('Zoom microphone is not ready')
        self.play_id += 1
        ident = self.play_id
        future = asyncio.get_running_loop().create_future()
        self.playbacks[ident] = future
        try:
            await self.send_packet(b'P', struct.pack('!I', ident) + pcm)
            await asyncio.wait_for(future, len(pcm) / 64000 + 5)
        except BaseException:
            await self.stop_speaking()
            raise
        finally:
            self.playbacks.pop(ident, None)

    async def stop_speaking(self):
        if self.writer and not self.writer.is_closing():
            with contextlib.suppress(Exception):
                await self.send_packet(b'C')

    def request_stop(self):
        self.stopped.set()

    async def leave(self):
        self.request_stop()
        await self.stop_speaking()
        if self.reader_task:
            self.reader_task.cancel()
            await asyncio.gather(self.reader_task, return_exceptions=True)
            self.reader_task = None
        if self.writer:
            self.writer.close()
            with contextlib.suppress(Exception):
                await self.writer.wait_closed()
            self.writer = None
        if self._owns_container:
            # Unique task-owned container only; never end the host's meeting.
            with contextlib.suppress(Exception):
                await self.docker('kill', '--signal', 'SIGINT', self.name)
                await self.docker('stop', '-t', '3', self.name)
            with contextlib.suppress(Exception):
                logs = await self.docker('logs', '--tail', '200', self.name)
                private_write(self.runtime / 'sdk.log', logs)
            try:
                await self.docker('rm', '-f', self.name)
            except RuntimeError:
                # A failed docker run may never have created the named container.
                remaining = await self.docker('ps', '-aq', '--filter', 'name=^/' + self.name + '$')
                if remaining:
                    self.on_event('zoom_cleanup_failed', container=self.name)
                    raise
            self._owns_container = False
        for name in ('config.txt', 'bridge-token'):
            (self.runtime / name).unlink(missing_ok=True)

    def diagnostics(self):
        return {'frames_received': self.frames_received, 'bytes_received': self.bytes_received,
                'raw_audio_saved': False, 'echo_mode': 'silence_during_playback_plus_350ms',
                'remote_audible_latency_measured': False}
