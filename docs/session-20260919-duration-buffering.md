# Session 20260919T173830-1f088270 follow-up

Baseline: 499fe7f. The changes were committed locally after coordinator verification.

The actual run ended normally: listening_ready at 13957 ms, session_stopped at 317441 ms, exit_reason=completed, and RECEIVER_STOPPED exit=0. ZoomAudioMeeting.audio exhausted the configured 300-second listening interval, followed by cleanup. It did not crash. Duration expiry now has its own successful duration_elapsed exit reason, session_duration_elapsed event, configured duration in run.json, and a deadline in listening_ready. Both Zoom CLI paths accept up to 3600 seconds; runnable conversation examples now use 3600. Expiry still ends unfinished playback/tasks rather than promising an unlimited session.

The run contains 12 playback_queue_full events followed by interruption/cancellation after 3200–4400 ms of SDK-submitted playback. The 15-second pending buffer was smaller than a permitted 120-second generated output. The aggregate pending PCM budget is now 120 seconds (7,680,000 bytes at 32 kHz), plus one in-flight 100ms packet and bounded resampling state. A 30-second generation burst now drains completely in the fake SDK regression. The exact 120-second boundary fits; longer individual output and aggregate overflow across items remain explicit failures. Cancellation reclaims queued PCM and resamplers. No PCM is silently dropped to make room.

Python previously reported echo gating without applying it. The native bridge already gates individual playback packets and their tails at callback time. Python now additionally gates at bridge receipt before its input queue, covering pending output, gaps between generated chunks, stalled SDK calls and the 350ms tail. A gate flag follows each frame; sample-position intervals carry the decision across resampler latency. Gated output chunks are equal-length zeros and both providers receive the same PCM. Coverage events use the actual frame marker. Tests hold gate-marked frames until after the gate expires and verify they stay silent.

Timing limit: this is bridge-receive timing, not a remote capture timestamp. The native protocol has no capture clock or gate marker. Native callback silence protects audio already queued upstream during actual SDK playback; Python adds a conservative wider window. Resampled chunks overlapping a gated interval are entirely silenced, which can extend coverage loss slightly. Speaker mode deliberately suppresses simultaneous human speech; it is not full-duplex AEC or voice barge-in.

There were 1127 zoom_playback_submitted events and 604 zoom_audio events. No console events were dropped; event volume is not established as the failure cause. Routine submission events are now rate-limited to once per five seconds in Realtime Zoom, while per-item first-submission events, D acknowledgements, interruption progress and all errors remain intact.

Coordinator real-meeting command:

```sh
ZOOM_PLATFORM=macos bash scripts/zoom.sh --language zh-CN --seconds 3600
```

Verify replies longer than 15 seconds finish audibly at another participant, several sequential turns do not trigger playback_queue_full, speech resumes after the echo tail, terminal interruption clears pending playback, and a short explicitly configured run reports duration_elapsed. Verify Ctrl+C reports stopped. No real meeting or remote-audibility test was performed for these changes. No native rebuild is required for this follow-up.

Validation: the coordinator reran 43 focused Realtime, Zoom audio, and session tests. The final full suite passed all 124 tests with `uv run --frozen python -m unittest discover -s tests -v`. `bash scripts/primitive.sh` passed with two silent mock WAV outputs; `bash scripts/demo.sh` passed with five mock events and one fixed reply. `git diff --check` passed.
