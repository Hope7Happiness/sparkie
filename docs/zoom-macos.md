# macOS Zoom bridge

Use official Meeting SDK 7.1.5 matching the host architecture. Set ZOOM_PLATFORM=macos and ZOOM_MACOS_SDK_PATH to the extracted root containing ZoomSDK/ZoomSDK.framework. Configure SDK credentials and meeting details in .env.

## Build and run

~~~bash
uv sync --frozen
uv run --frozen python scripts/zoom-sanity.py build --platform macos
uv run --frozen python scripts/zoom-sanity.py check --platform macos
~~~

Build uses the local SDK and native/zoom-macos/main.m. Rebuild after native or SDK changes. Check only loads/initializes the SDK; it does not authenticate or join. Handle Keychain/microphone permission requests through macOS.

Run each command in a separate terminal:

~~~bash
uv run --frozen sparkie workspace --host 0.0.0.0 --port 8790 --worker devin
npm --prefix frontend run dev
ZOOM_PLATFORM=macos bash scripts/zoom.sh --language en-US --seconds 3600
~~~

Host admission, raw-audio access and sharing permission are separate requirements. Wait for listening_ready. SDK authentication or an accepted join request alone does not prove admission or audio readiness.

## Receive-only diagnostics

~~~bash
uv run --frozen python scripts/zoom-sanity.py start --platform macos
uv run --frozen python scripts/zoom-sanity.py logs --platform macos
uv run --frozen python scripts/zoom-sanity.py stop --platform macos
~~~

The separate probe checks admission/audio reception without model calls. Stopping log viewing does not stop the probe. Do not run it alongside another process using the same receiver resources.

## Audio and sharing

The bridge publishes mixed A frames, participant U frames and metadata. Participant mode excludes the SDK self-track and uses final participant transcripts as foreground input. cancel-v1 provides an acknowledged playback barrier. Microphone callback readiness is required before playback; mute is distinct from playback failure.

The V command loads the full frontend workspace in WKWebView. Native sharing emits 1280x720 I420 snapshots with at most one pending capture. App-window fallback needs screen-recording permission. Frontend/backend must remain reachable. Returning from a report preserves the shared board.

Join has a bounded total deadline with distinct connecting, host/waiting-room, SDK and audio-readiness failures. Startup audio is explicitly discarded until readiness. Cleanup terminates only the session-owned receiver. Verify complete audio and readable content from another Zoom participant; local compilation and tests cannot establish remote delivery.
