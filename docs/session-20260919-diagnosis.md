# Session failure investigation: 20260919T172021-be4b6860

Base commit: `44039cf2ead653c5f49d73a89b534a2eb8175153`. Fix is uncommitted, on top of the existing intentional Zoom/Realtime work.

The exact historical ProviderError cannot be recovered from the four supplied artifacts: the session handler persisted only the exception class, with no message, traceback, or provider failure details. Do not close the reported meeting failure as verified.

Evidence: Realtime and Deepgram were ready at 1.733/1.734 seconds; Zoom audio opened at 21.031 seconds. Two Realtime responses completed. The third began at 55.383 seconds; SDK playback submissions continued through 60.852 seconds, but no third response completion or assistant transcript was recorded. Input continued through failure at 61.796 seconds (maximum receive gap 24 ms). There is no provider_error, failed response.done, audio_failed, or audio_backpressure coverage record. SDK log ends with RECEIVER_STOPPED exit=0. These observations do not establish a network disconnect or playback overflow; raw provider events and queue occupancy were not saved. Deepgram emitted only one human transcript; its missing later transcripts remain unverified.

A reproducible local defect is that generation exceeding the bounded 15-second Zoom playback queue raises ProviderError from RealtimeZoomAudio.enqueue and kills the entire session. An offline regression failed with that precise traceback before the fix. The fix retains the bound and cancels/truncates the affected reply through the existing interruption path, discarding late chunks and allowing a subsequent reply. It does not guarantee delivery of the full oversized reply. This is a candidate failure path, not proof of the historical cause.

Diagnostics now retain allowlisted reasons/provider codes and local code locations in session_failed and run.json.failure. Unknown values are labeled rather than copied; raw exception/provider bodies are never logged. Failed response.done now emits sanitized provider_error details.

Verification commands:

```sh
uv run --frozen python -m unittest discover -s tests -p 'test_realtime*.py' -v
uv run --frozen python -m unittest discover -s tests -v
bash scripts/primitive.sh
bash scripts/demo.sh
```

Real meeting validation remains: rerun the original scenario, verify another participant hears the replies, try a long reply followed by another request, and check continued human transcription and background task completion. Inspect realtime_playback_limited or the new failure details if the problem recurs. No real meeting, live inference, commit, or push was performed during this investigation.

Verification results: 28 focused Realtime tests passed; all 113 tests passed; primitive simulation exited 0 with two silent mock WAV outputs; demo simulation exited 0 with five events and one fixed text reply. `git diff --check` passed. These are offline checks, not evidence of real platform capability.
