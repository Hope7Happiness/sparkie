# macOS Zoom voice debug, 2026-09-19

Tested merged commit `ab3035a` on this Apple Silicon Mac with official Meeting SDK 7.1.5.84750. Build and SDK initialization succeeded with Command Line Tools and macOS SDK 26.4 (full Xcode was not installed).

## Real meeting evidence

- SDK authentication succeeded (`SDK_AUTH_RESULT result=0`).
- Host admitted Sparkie; native callback reached `state=3` / `In Meeting Now...`.
- Virtual microphone initialized; host granted recording permission; Python received `zoom_audio_ready`, 32000 Hz mono.
- Raw receive callbacks arrived, but the host stayed muted: this does **not** establish non-silent incoming speech or STT correctness.
- Host-side Web Audio capture contained nonzero output from the bot. Capture reported zero worklet gaps.
- Playback failed to complete. The first attempt sent 135 frames before timeout, with inter-frame gaps of 47–133 ms (target 20 ms), SDK send calls at most 8 ms. A 1280-byte frame represents 20 ms of 32 kHz mono PCM16.
- A second real-meeting experiment with interactive thread QoS and an NSProcessInfo latency-critical activity sent 138 frames, gaps 22–130 ms, 135 gaps over 40 ms, and again timed out. The change was reverted because it did not resolve the problem.
- Both test bots left the meeting; private per-run config was removed.

## Independent timing experiments

Without Zoom, 100 Python sleeps requested at 20 ms averaged 103.8 ms. A C `mach_wait_until` experiment with interactive QoS averaged 107.4 ms; a successfully applied time-constraint thread policy still averaged 105.7 ms. These establish severe timing delays in this machine/session during the test. They do not identify the underlying OS/hardware cause or prove that all audio defects come from scheduling.

Do not compensate by bursting stale PCM or claim that a longer timeout fixes audio quality. Next acceptance run should first establish reliable 20 ms timing, then complete both full utterances and verify non-silent incoming speech and Q&A. A different machine is a useful independent comparison; changing global system settings or restarting other apps was not attempted.

## Artifacts and checks

Local, ignored artifacts: `output/zoom-quality-macos/before.wav`, `after.wav`, `summary.json`; `.runtime/zoom-quality-macos.log`, `zoom-quality-macos-fixed.log`, and `.runtime/zoom-quality-macos/sdk.log` (latest run). The first WAV includes the incomplete initial playback; the second includes the unsuccessful QoS experiment. Inspect SDK logs before sharing externally.

93 Python tests passed; offline primitive and demo passed. Native build/signature and SDK loading passed. These do not replace real audio acceptance.

The newly merged GPT Realtime frontend remains a browser/local transport. This test exercised the native Zoom PCM bridge, not a Realtime-to-Zoom integration, and did not complete Q&A acceptance.
