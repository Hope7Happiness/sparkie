"""Sanitized macOS receiver startup evidence; no SDK imports or native changes."""
import re
import time

from .providers import ProviderError

# Installed macOS SDK 7.1.5 ZoomSDKErrors.h (not Linux enum values).
STATES = {0: 'idle', 1: 'connecting', 2: 'waiting_for_host', 3: 'in_meeting',
          4: 'disconnecting', 5: 'reconnecting', 6: 'failed', 7: 'ended',
          8: 'audio_ready', 9: 'other_meeting_in_progress', 10: 'waiting_room'}
HINTS = {
    'connecting': 'Zoom has not reached admission. Check host meeting availability and local network/VPN; no SDK cause was reported.',
    'waiting_for_host': 'Ask the host to start the configured meeting.',
    'waiting_room': 'Ask the host to admit Sparkie from the waiting room.',
    'in_meeting': 'Check computer audio, recording permission and virtual microphone readiness.',
    'audio_ready': 'Audio connection is reported; still waiting for meeting admission and raw audio/microphone readiness.',
}


class ZoomJoinError(ProviderError):
    def __init__(self, reason, fields):
        # All callers supply fixed reasons and the sanitized snapshot below.
        super().__init__('Zoom join: ' + reason)
        self.reason, self.fields = reason, fields

    def diagnostic_fields(self):
        return {'provider': 'zoom', 'reason': self.reason, **self.fields}


class NativeJoinProgress:
    def __init__(self, path, clock=time.monotonic):
        self.path, self.clock = path, clock
        self.offset = 0
        self.partial = b''
        self.discard_line = False
        self.state = self.error = self.end_reason = None
        self.changed_at = None
        self.stage, self.result = 'not_observed', None
        self.failure = None

    def feed_line(self, line):
        match = re.fullmatch(rb'MEETING_STATUS state=([0-9]{1,5}) error=([0-9]{1,5}) reason=([0-9]{1,5})', line)
        if match:
            values = tuple(map(int, match.groups()))
            if values != (self.state, self.error, self.end_reason):
                self.changed_at = self.clock()
            self.state, self.error, self.end_reason = values
            if self.state in (6, 7):
                self.failure = 'meeting_failed' if self.state == 6 else 'meeting_ended_before_audio'
            return True
        match = re.fullmatch(rb'(SDK_INIT|SDK_AUTH_REQUEST|SDK_AUTH_RESULT|MUTE_ON_JOIN|JOIN_REQUEST) result=(-?[0-9]{1,5})', line)
        if match:
            self.stage, self.result = match[1].decode(), int(match[2])
            if self.result != 0:
                self.failure = {'SDK_INIT': 'sdk_init_failed', 'SDK_AUTH_REQUEST': 'sdk_auth_failed',
                                'SDK_AUTH_RESULT': 'sdk_auth_failed', 'MUTE_ON_JOIN': 'mute_on_join_failed',
                                'JOIN_REQUEST': 'join_request_failed'}[self.stage]
            return True
        return False

    def read(self):
        # Native stdout contains third-party diagnostics too: never forward raw lines.
        # Bound each poll and line buffer even if an SDK writes an enormous line.
        try:
            with self.path.open('rb') as stream:
                if self.path.stat().st_size < self.offset:
                    self.offset = 0
                    self.partial = b''
                    self.discard_line = False
                stream.seek(self.offset)
                data = stream.read(65536)
                self.offset += len(data)
        except FileNotFoundError:
            return []
        snapshots = []
        for chunk in data.splitlines(keepends=True):
            self.partial += chunk
            if len(self.partial) > 512:
                self.discard_line = True
                self.partial = b''
            if chunk.endswith(bytes([10])):
                if not self.discard_line and self.feed_line(self.partial.rstrip(bytes([13, 10]))):
                    snapshots.append(self.snapshot())
                self.partial = b''
                self.discard_line = False
        return snapshots

    def snapshot(self):
        fields = {'native_stage': self.stage}
        if self.result is not None:
            fields['sdk_result'] = self.result
        if self.state is not None:
            name = STATES.get(self.state, 'unknown')
            fields.update(meeting_state=self.state, meeting_state_name=name,
                          meeting_error=self.error, meeting_end_reason=self.end_reason,
                          state_observed_ms=round((self.clock() - self.changed_at) * 1000),
                          hint=HINTS.get(name, 'Inspect the last meeting state and verify the current meeting configuration with the host.'))
        else:
            fields['hint'] = 'Check native startup/system permission prompts and SDK authentication progress.'
        return fields

    def timeout_reason(self):
        return {1: 'connecting_timeout', 2: 'waiting_for_host_timeout',
                10: 'waiting_room_timeout', 3: 'audio_readiness_timeout',
                8: 'audio_readiness_timeout', 5: 'reconnecting_timeout'}.get(self.state, 'join_timeout')
