#!/usr/bin/env python3
"""Local Zoom receive-only sanity runner; requires the prepared 7.0.5 image."""
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import time

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
NAME = 'sparkie-zoom-receiver'
IMAGE = 'sparkie-zoom-sanity:7.0.5'


def docker(*args, **kwargs):
    return subprocess.run(['docker', *args], check=True, **kwargs)


def start():
    load_dotenv(ROOT / '.env')
    required = ['ZOOM_CLIENT_ID', 'ZOOM_CLIENT_SECRET', 'ZOOM_MEETING_ID', 'ZOOM_MEETING_PASSWORD']
    if missing := [key for key in required if not os.getenv(key)]:
        raise SystemExit('Missing: ' + ', '.join(missing))
    existing = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', NAME], capture_output=True, text=True)
    if existing.returncode == 0:
        if existing.stdout.strip() == 'true':
            print('Receiver already running. Use logs or stop.')
            return
        docker('rm', NAME, stdout=subprocess.DEVNULL)
    check = subprocess.run(['docker', 'image', 'inspect', IMAGE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if check.returncode:
        raise SystemExit('Prepared image missing; see docs/zoom-sanity.md.')
    issued = int(time.time()) - 30
    payload = {'appKey': os.environ['ZOOM_CLIENT_ID'], 'iat': issued,
               'exp': issued + 3600, 'tokenExp': issued + 3600,
               'mn': os.environ['ZOOM_MEETING_ID'], 'role': 0}
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b'=')
    body = b'.'.join(encode(json.dumps(x, separators=(',', ':')).encode())
                     for x in ({'alg': 'HS256', 'typ': 'JWT'}, payload))
    token = (body + b'.' + encode(hmac.new(os.environ['ZOOM_CLIENT_SECRET'].encode(), body, hashlib.sha256).digest())).decode()
    config = ROOT / '.runtime/zoom-sanity/live-config.txt'
    config.parent.mkdir(parents=True, exist_ok=True)
    values = {'meeting_number': os.environ['ZOOM_MEETING_ID'], 'token': token,
              'meeting_password': os.environ['ZOOM_MEETING_PASSWORD'],
              'recording_token': '', 'onBehalfOf_Token': '',
              'GetVideoRawData': 'false', 'GetAudioRawData': 'true',
              'SendVideoRawData': 'false', 'SendAudioRawData': 'false'}
    # The upstream sample uses a simple quoted, line-based format.
    if any(any(c in v for c in '\n\r"') for v in values.values()):
        raise SystemExit('Configuration contains characters unsupported by the sample parser.')
    fd = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as out:
        os.fchmod(out.fileno(), 0o600)
        out.write(''.join(f'{k}: "{v}"\n' for k, v in values.items()))
    docker('run', '-d', '--name', NAME, '--platform', 'linux/arm64',
           '-v', f'{config}:/run/config.txt:ro', IMAGE, '/bin/bash', '-lc',
           'cp /run/config.txt /app/demo/bin/config.txt; '
           'bash /app/demo/setup-pulseaudio.sh >/tmp/audio-setup.log 2>&1; '
           'exec /app/demo/bin/meetingSDKDemo', stdout=subprocess.DEVNULL)
    print('Sparkie receiver started. Host must start the configured meeting, admit Sparkie, and grant recording permission.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['start', 'logs', 'stop'])
    command = parser.parse_args().command
    if command == 'start':
        start()
    elif command == 'logs':
        docker('logs', '--tail', '50', '-f', NAME)
    else:
        docker('kill', '--signal', 'SIGINT', NAME)
        docker('stop', '-t', '5', NAME, stdout=subprocess.DEVNULL)
