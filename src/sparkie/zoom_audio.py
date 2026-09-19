"""Real Zoom PCM adapter; the SDK process sees only Zoom credentials, never provider keys."""
import asyncio
import contextlib
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import time

from .audio import AudioFrame
from .providers import failure_details
from .zoom_errors import ZoomBridgeError
from .zoom_config import meeting_config, private_write


class ZoomAudioMeeting:
    """Linux Docker bridge; the SDK runs in a container, the host speaks framed PCM."""

    def __init__(self, runtime, *, max_seconds=300, join_timeout=120):
        self.runtime = Path(runtime).resolve()
        self.max_seconds, self.join_timeout = max_seconds, join_timeout
        self.name = 'sparkie-zoom-voice-' + secrets.token_hex(4)
        self.reader = self.writer = self.reader_task = None
        self.port = None
        self._token = None
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
        self.frames_consumed = self.max_queued_frames = 0
        self.max_receive_gap_ms = 0
        self._last_audio_at = None
        self.audio_origin = None  # Network input does not establish a remote acoustic clock.
        self.last_playback_started_at = None  # SDK acceptance is not a DAC timestamp.
        self._owns_container = False
        self._write_lock = asyncio.Lock()
        self.input_gate = lambda: False
        self.duration_expired = False
        self.playback_event_interval = 0.0
        self._last_playback_event = float('-inf')
        self._control_lock = asyncio.Lock()
        self._cancel_id = 0
        self._cancel_waiter = None
        self.cancel_timeout = 5.0

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

    async def launch(self):
        """Start the native SDK side and set self.port/self._token for connect()."""
        config = meeting_config()
        values = {k: config[k] for k in ('meeting_number', 'token', 'meeting_password')}
        values.update(recording_token='', onBehalfOf_Token='', GetVideoRawData='false',
                      GetAudioRawData='true', SendVideoRawData='false', SendAudioRawData='true')
        if any(any(c in v for c in '\n\r"') for v in values.values()):
            raise ValueError('Zoom configuration contains unsupported characters')
        self.runtime.mkdir(parents=True, exist_ok=True)
        self._token = secrets.token_hex(32)
        private_write(self.runtime / 'bridge-token', self._token)
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
        self.port = int((await self.docker('port', self.name, '8769/tcp')).rsplit(':', 1)[1])

    def connect_context(self):
        return {'container': self.name}

    def launch_failure(self):
        return None

    async def connect(self):
        while True:
            failure = self.launch_failure()
            if failure:
                raise failure
            try:
                self.reader, self.writer = await asyncio.open_connection('127.0.0.1', self.port)
                self.writer.write(self._token.encode())
                await self.writer.drain()
                # The SDK side can accept TCP before its bridge starts listening.
                kind, payload = await self.read_packet()
                if kind != b'H' or payload != b'cancel-v1':
                    self.failure = RuntimeError('Zoom bridge requires cancel-v1; rebuild the native receiver')
                    raise self.failure
                return
            except (OSError, asyncio.IncompleteReadError):
                if self.writer:
                    self.writer.close()
                    await self.writer.wait_closed()
                await asyncio.sleep(.5)

    async def join(self):
        await self.launch()
        self.on_event('zoom_connecting', hint='Host must admit Sparkie and allow recording for audio access.',
                      **self.connect_context())
        async with asyncio.timeout(self.join_timeout):
            await self.connect()
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
                    now = time.monotonic()
                    if self._last_audio_at is not None:
                        self.max_receive_gap_ms = max(self.max_receive_gap_ms, round((now - self._last_audio_at) * 1000))
                    self._last_audio_at = now
                    self.frames_received += 1
                    self.bytes_received += len(data)
                    self.audio_ready.set()
                    if self.queue.qsize() >= 250 and not self._backlogged:
                        self._backlogged = True
                        self.on_event("audio_warning", reason="zoom_input_backlog", queued_frames=self.queue.qsize())
                    # Decide before queuing: queued echo must stay silent after the gate closes.
                    gated = self.input_gate()
                    self.queue.put_nowait(AudioFrame(self.frames_received, bytes(len(data)) if gated else data,
                                                     gated=gated))
                    self.max_queued_frames = max(self.max_queued_frames, self.queue.qsize())
                    if self.frames_received % 32 == 0:
                        # StreamReader may return buffered packets without suspending.
                        # Give the STT consumer time to drain after a transport burst.
                        await asyncio.sleep(0)
                    if self.frames_received % 50 == 0:
                        self.on_event('zoom_audio', frames=self.frames_received, queued_frames=self.queue.qsize(),
                                      consumed_frames=self.frames_consumed, max_receive_gap_ms=self.max_receive_gap_ms,
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
                            now = time.monotonic()
                            if now - self._last_playback_event >= self.playback_event_interval:
                                self._last_playback_event = now
                                self.on_event('zoom_playback_submitted', playback_id=ident,
                                              note='SDK accepted first frame; remote audible latency is not measured.')
                        elif not entry.done():
                            entry.set_result(None)
                elif kind == b'K' and len(data) == 4:
                    ident = struct.unpack('!I', data)[0]
                    if ident == self._cancel_id and self._cancel_waiter and not self._cancel_waiter.done():
                        self._cancel_waiter.set_result(None)
                elif kind == b'E':
                    raise ZoomBridgeError(data)
                else:
                    raise RuntimeError('Invalid Zoom bridge event')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.failure = exc
            # Resolve control waiters before diagnostics: a broken event sink must
            # never hide the primary failure behind a second playback timeout.
            for future in self.playbacks.values():
                if not future.done():
                    future.set_exception(exc)
            if self._cancel_waiter and not self._cancel_waiter.done():
                self._cancel_waiter.set_exception(exc)
            self.stopped.set()
            self.on_event('audio_failed', **failure_details(exc))

    async def audio(self):
        started = time.monotonic()
        while not self.stopped.is_set() and time.monotonic() - started < self.max_seconds:
            try:
                frame = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                try:
                    frame = await asyncio.wait_for(self.queue.get(), .1)
                except TimeoutError:
                    continue
            if self._backlogged and self.queue.qsize() < 50:
                self._backlogged = False
                self.on_event("zoom_input_recovered")
            self.frames_consumed += 1
            yield frame
        if self.failure:
            raise self.failure
        if not self.stopped.is_set():
            self.duration_expired = True

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
            async with self._control_lock:
                await self.send_packet(b'P', struct.pack('!I', ident) + pcm)
            await asyncio.wait_for(future, len(pcm) / 64000 + 5)
        except BaseException:
            if not self.failure:
                await self.stop_speaking()
            raise
        finally:
            self.playbacks.pop(ident, None)

    async def stop_speaking(self):
        async with self._control_lock:
            if self.failure:
                raise self.failure
            if not self.writer or self.writer.is_closing():
                return
            self._cancel_id += 1
            future = self._cancel_waiter = asyncio.get_running_loop().create_future()
            try:
                async with asyncio.timeout(self.cancel_timeout):
                    await self.send_packet(b'C', struct.pack('!I', self._cancel_id))
                    await future
            except BaseException as exc:
                # Never reuse a connection whose cancellation boundary is unknown.
                self.failure = (RuntimeError('Zoom cancellation acknowledgement timed out')
                                if isinstance(exc, TimeoutError) else
                                RuntimeError('Zoom cancellation aborted') if isinstance(exc, asyncio.CancelledError) else exc)
                self.stopped.set()
                self.writer.close()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise self.failure from None
            finally:
                if not future.done():
                    future.cancel()
                self._cancel_waiter = None

    def request_stop(self):
        self.stopped.set()

    async def _disconnect(self):
        self.request_stop()
        with contextlib.suppress(Exception):
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

    async def leave(self):
        await self._disconnect()
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
                'frames_consumed': self.frames_consumed, 'max_queued_frames': self.max_queued_frames,
                'max_receive_gap_ms': self.max_receive_gap_ms, 'raw_audio_saved': False, 'echo_mode': 'silence_during_playback_plus_350ms',
                'remote_audible_latency_measured': False}


class ZoomMacAudioMeeting(ZoomAudioMeeting):
    """Same loopback bridge protocol without Docker; launches the signed macOS receiver app."""

    def __init__(self, runtime, binary, **kwargs):
        super().__init__(runtime, **kwargs)
        self.binary = Path(binary)
        self.name = 'sparkie-zoom-macos-' + secrets.token_hex(4)
        self.process = None
        self._log = None

    async def launch(self):
        from .zoom_macos import child_env
        if not self.binary.is_file():
            raise ValueError('Build the macOS receiver first: zoom-sanity.py build --platform macos')
        config = meeting_config()
        self._token = secrets.token_hex(32)
        # Reserve an ephemeral loopback port; the app binds it when the bridge starts.
        probe = socket.socket()
        probe.bind(('127.0.0.1', 0))
        self.port = probe.getsockname()[1]
        probe.close()
        config.update(voice=True, bridge_port=self.port, bridge_token=self._token)
        self.runtime.mkdir(parents=True, exist_ok=True)
        config_path = self.runtime / 'config.json'
        private_write(config_path, json.dumps(config))
        private_write(self.runtime / 'sdk.log', '')
        self._log = (self.runtime / 'sdk.log').open('ab')
        env = child_env()
        env['SPARKIE_ZOOM_CONFIG'] = str(config_path)
        self.process = await asyncio.create_subprocess_exec(
            str(self.binary), env=env, stdin=asyncio.subprocess.DEVNULL,
            stdout=self._log, stderr=asyncio.subprocess.STDOUT, start_new_session=True)

    def connect_context(self):
        return {'binary': str(self.binary)}

    def launch_failure(self):
        if self.process is not None and self.process.returncode is not None:
            return RuntimeError('Zoom macOS receiver exited during join; inspect sdk.log')
        return None

    async def leave(self):
        await self._disconnect()
        process, self.process = self.process, None
        if process and process.returncode is None:
            # SIGTERM lets the app leave the meeting; never end the host's meeting.
            with contextlib.suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 10)
            except (asyncio.TimeoutError, ProcessLookupError):
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.wait(), 5)
        if self._log:
            self._log.close()
            self._log = None
        (self.runtime / 'config.json').unlink(missing_ok=True)
