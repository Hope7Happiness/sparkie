#!/usr/bin/env python3
"""Overlay the voice bridge on the pinned, already prepared receive-only image."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'sparkie-zoom-sanity:7.0.5'

def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)

build = ROOT / '.runtime/zoom-voice-build'
build.mkdir(parents=True, exist_ok=True)
container = run('docker', 'create', BASE, capture_output=True, text=True).stdout.strip()
try:
    for name in ('meeting_sdk_demo.cpp', 'CMakeLists.txt'):
        run('docker', 'cp', f'{container}:/app/demo/{name}', str(build / name))
finally:
    run('docker', 'rm', container, stdout=subprocess.DEVNULL)
source = (build / 'meeting_sdk_demo.cpp').read_text()
source = '#include "VoiceBridge.h"\n' + source
# Start once before authentication; source is from the pinned receive-only image.
needle = 'int main('
assert source.count(needle) == 1
at = source.index('{', source.index(needle)) + 1
source = source[:at] + '\n    bridgeStart();\n' + source[at:]
# Install the virtual mic before unmuting; never enable physical input or video.
needle = '\tCheckAndStartRawSending(SendVideoRawData, SendAudioRawData);'
assert source.count(needle) == 1
source = source.replace(needle, needle + '\n    if (SendAudioRawData) turnOnSendVideoAndAudio();')
(build / 'meeting_sdk_demo.cpp').write_text(source)
cmake = (build / 'CMakeLists.txt').read_text().replace('add_executable(meetingSDKDemo', 'add_executable(meetingSDKDemo ${CMAKE_SOURCE_DIR}/VoiceBridge.cpp')
(build / 'CMakeLists.txt').write_text(cmake)
for path in (ROOT / 'native/zoom-linux').iterdir():
    shutil.copy2(path, build / path.name)
(build / 'Dockerfile').write_text('FROM '+BASE+'\nCOPY *.cpp *.h CMakeLists.txt /app/demo/\nRUN cmake -S /app/demo -B /app/demo/build && cmake --build /app/demo/build -j3\n')
run('docker', 'build', '--platform', 'linux/arm64', '-t', 'sparkie-zoom-voice:7.0.5', str(build))
