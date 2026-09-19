#!/usr/bin/env python3
"""Receive-only Zoom probes: Linux Docker (default) or native macOS."""
import argparse
from pathlib import Path
import subprocess

from dotenv import load_dotenv
from sparkie.zoom_config import meeting_config, private_write, selected_platform

ROOT = Path(__file__).resolve().parents[1]
NAME = 'sparkie-zoom-receiver'
IMAGE = 'sparkie-zoom-sanity:7.0.5'


def docker(*args, **kwargs):
    return subprocess.run(['docker', *args], check=True, **kwargs)


def start():
    credentials = meeting_config()
    existing = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', NAME], capture_output=True, text=True)
    if existing.returncode == 0:
        if existing.stdout.strip() == 'true':
            print('Receiver already running. Use logs or stop.')
            return
        docker('rm', NAME, stdout=subprocess.DEVNULL)
    check = subprocess.run(['docker', 'image', 'inspect', IMAGE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if check.returncode:
        raise SystemExit('Prepared image missing; see docs/zoom-sanity.md.')
    config = ROOT / '.runtime/zoom-sanity/live-config.txt'
    config.parent.mkdir(parents=True, exist_ok=True)
    values = {'meeting_number': credentials['meeting_number'], 'token': credentials['token'],
              'meeting_password': credentials['meeting_password'],
              'recording_token': '', 'onBehalfOf_Token': '',
              'GetVideoRawData': 'false', 'GetAudioRawData': 'true',
              'SendVideoRawData': 'false', 'SendAudioRawData': 'false'}
    # The upstream sample uses a simple quoted, line-based format.
    if any(any(c in v for c in '\n\r"') for v in values.values()):
        raise SystemExit('Configuration contains characters unsupported by the sample parser.')
    private_write(config, ''.join(f'{k}: "{v}"\n' for k, v in values.items()))
    docker('run', '-d', '--name', NAME, '--platform', 'linux/arm64',
           '-v', f'{config}:/run/config.txt:ro', IMAGE, '/bin/bash', '-lc',
           'cp /run/config.txt /app/demo/bin/config.txt; '
           'bash /app/demo/setup-pulseaudio.sh >/tmp/audio-setup.log 2>&1; '
           'exec /app/demo/bin/meetingSDKDemo', stdout=subprocess.DEVNULL)
    print('Sparkie receiver started. Host must start the configured meeting, admit Sparkie, and grant recording permission.')


def main():
    load_dotenv(ROOT / '.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['build', 'check', 'start', 'logs', 'stop'])
    parser.add_argument('--platform', choices=['linux', 'macos'], default=None,
                        help='Overrides ZOOM_PLATFORM; defaults to linux for compatibility')
    args = parser.parse_args()
    try:
        target = args.platform or selected_platform()
        if target == 'macos':
            from sparkie.zoom_macos import run
            run(args.command, ROOT)
        elif args.command == 'start':
            start()
        elif args.command == 'logs':
            docker('logs', '--tail', '50', '-f', NAME)
        elif args.command == 'stop':
            docker('kill', '--signal', 'SIGINT', NAME)
            docker('stop', '-t', '5', NAME, stdout=subprocess.DEVNULL)
        else:
            parser.error('Linux build and verification steps are in docs/zoom-sanity.md')
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
