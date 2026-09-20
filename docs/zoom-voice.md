# Zoom Realtime voice

The supported voice path uses Realtime, Deepgram transcripts and a Devin/Codex worker. The fixed-reply wake/qa TTS pipeline has been removed.

Follow [macOS setup](zoom-macos.md) or [Linux build](zoom-sanity.md), configure [credentials](manual-setup.md), then run:

~~~bash
bash scripts/zoom.sh --language en-US --seconds 3600
~~~

On macOS, run workspace and frontend services before joining to share artifacts. Linux supplies mixed audio; macOS participant tracks and WebView sharing are not implied to work there.

Wait for listening_ready. Test addressed questions, ordinary discussion that should remain silent, follow-ups, real tasks, interruption and report selection/return to the board. Verify audio and sharing from another participant device.

Session records live under output/zoom/<session>/. Inspect readiness, failures, coverage gaps and task status before retrying. Native playback progress is not proof of remote delivery. Session termination stops background work.

See [Realtime operation](realtime.md), [semantic turns](semantic-turn-detection.md) and [contracts](interfaces.md).
