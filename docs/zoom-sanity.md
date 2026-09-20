# Linux Zoom SDK build

This workflow uses official Linux ARM64 Meeting SDK 7.0.5.3529 with a pinned sample in Docker. Download the SDK separately and set ZOOM_SDK_PATH to the directory containing h/, libmeetingsdk.so, qt_libs/, libglib2/ and json/. Other SDK versions/architectures need separate validation.

Configure credentials and meeting details in .env. Docker must be running. macOS users should use [the native bridge](zoom-macos.md).

## Prepare the receive-only image

From the repository root, after uv sync --frozen:

~~~bash
mkdir -p .runtime
git clone https://github.com/zoom/meetingsdk-linux-raw-recording-sample.git .runtime/zoom-sanity-source
git -C .runtime/zoom-sanity-source checkout ed7e1fe12b0dcbf0a215079bb877077703da03fa
git -C .runtime/zoom-sanity-source apply ../../docs/zoom-sanity-assets/receive-only.patch

uv run --frozen python - <<'PY'
import os
from pathlib import Path
import shutil
from dotenv import load_dotenv

load_dotenv('.env')
sdk = Path(os.environ['ZOOM_SDK_PATH']).expanduser()
for name in ('h', 'libmeetingsdk.so', 'qt_libs', 'libglib2', 'json'):
    if not (sdk / name).exists():
        raise SystemExit(f'SDK missing {name}; check ZOOM_SDK_PATH and version')
build = Path('.runtime/zoom-sanity-7.0.5')
if build.exists():
    raise SystemExit('Build directory exists; reuse it for docker build instead of initializing again')
shutil.copytree('.runtime/zoom-sanity-source/demo', build / 'demo')
demo = build / 'demo'
shutil.rmtree(demo / 'include', ignore_errors=True)
shutil.copytree(sdk / 'h', demo / 'include/h')
libs = demo / 'lib/zoom_meeting_sdk'
shutil.rmtree(libs, ignore_errors=True)
libs.mkdir(parents=True)
for name in ('libmeetingsdk.so', 'qt_libs', 'libglib2', 'json'):
    source = sdk / name
    if source.is_dir():
        shutil.copytree(source, libs / name)
    else:
        shutil.copy2(source, libs / name)
assets = Path('docs/zoom-sanity-assets')
for name in ('Dockerfile', '.dockerignore'):
    shutil.copy2(assets / name, build / name)
shutil.copy2(assets / 'config.txt', demo / 'config.txt')
print('Build directory prepared')
PY

docker build --platform linux/arm64 -t sparkie-zoom-sanity:7.0.5 .runtime/zoom-sanity-7.0.5
~~~

The Dockerfile and patch live in docs/zoom-sanity-assets/. SDK binaries are not committed. For model-free reception diagnostics use start/logs/stop through scripts/zoom-sanity.py --platform linux. The host must admit Sparkie and grant recording permission. Callbacks alone do not prove non-silent speech.

## Voice

~~~bash
uv run --frozen python scripts/build-zoom-voice.py
ZOOM_PLATFORM=linux bash scripts/zoom.sh --language en-US --seconds 600
~~~

The voice build overlays native/zoom-linux on the prepared image. Realtime handles speech; Deepgram and the worker need separate configuration. Linux uses mixed audio and does not implement macOS participant-track or WebView sharing. Verify full remote speech and cleanup in a real meeting.
