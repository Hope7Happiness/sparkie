"""Decode the native Zoom bridge's bounded, allowlisted error protocol."""
import json

from .providers import ProviderError


class ZoomBridgeError(ProviderError):
    REASONS = {'sdk_send_failed', 'playback_active', 'microphone_unavailable',
               'invalid_input_format', 'unknown_native_error'}
    LEGACY = {
        b'Zoom virtual microphone could not send audio': 'sdk_send_failed',
        b'Playback is already active': 'playback_active',
        b'Zoom virtual microphone is muted or unavailable': 'microphone_unavailable',
        b'Expected mono PCM16 32000 Hz from Zoom': 'invalid_input_format',
    }

    def __init__(self, payload):
        reason = self.LEGACY.get(payload, 'unknown_native_error')
        self.fields = {}
        if len(payload) <= 512:
            try:
                data = json.loads(payload)
            except (ValueError, UnicodeError):
                data = None
            if isinstance(data, dict) and type(data.get('version')) is int and data['version'] == 1:
                candidate = data.get('reason')
                if isinstance(candidate, str) and candidate in self.REASONS:
                    reason = candidate
                    for key, low, high in [('sdk_result', -1, 2147483647),
                                           ('playback_id', 0, 4294967295),
                                           ('frame_index', 0, 1500)]:
                        value = data.get(key)
                        if type(value) is int and low <= value <= high:
                            self.fields[key] = value
        self.reason = reason
        super().__init__('Zoom bridge: ' + reason)

    def diagnostic_fields(self):
        return {'provider': 'zoom', 'reason': self.reason, **self.fields}
