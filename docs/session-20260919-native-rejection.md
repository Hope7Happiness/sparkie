# Immediate native playback rejection: 20260919T172803-1badab58

This follow-up supersedes any suggestion that the 15-second queue fix resolves the reported meeting failure. It was developed from commit f239345 and committed locally after verification.

## Evidence and confidence

The supplied events show first SDK acceptance at 21.634 seconds, two audio_failed events at 21.679 seconds, and session_failed at 21.780 seconds. The exception source is the native E branch in zoom_audio.receive. Native BRIDGE_PLAYBACK records three attempted frames, 22 ms gaps, and max_send_ms=0. No microphone-stop event is recorded. Only one playback packet was started. The third attempted frame is inside the first 100 ms packet, not its padded final frame.

High confidence: this is an immediate native bridge rejection, not the 15-second Python queue limit. Strongest explanation: the third send returned a non-success SDK result. The old bridge discarded the numeric result and Python discarded the E payload, so the exact status and underlying SDK cause cannot be established. Another native E source cannot be ruled out absolutely. No evidence supports diagnosing TooFrequentCall, mute, wrong thread, or unsupported PCM here.

## Installed SDK contract inspected

Local SDK: /Users/flyfishyu/Downloads/zoom-sdk-macos-7.1.5.84750. Headers also exist under .runtime/zoom-macos/staging/SparkieZoom.app/Contents/Frameworks/ZoomSDK.framework/Versions/A/Headers.

ZoomSDKRawDataAudioSourceController.h lines 18–25 specifies 16-bit samples, an even byte length, mono 32000 Hz among supported rates, and Success or an error return. Lines 34–50 specify initialization with a nullable sender, StartSend permission, StopSend cessation, and uninitialization. No sending-thread restriction, required frame duration, post-return buffer ownership rule, or transient retry policy is stated there. Searching installed ZoomSDKSample source found no virtual microphone send example. We retain the existing synchronous buffer lifetime and worker thread rather than inventing restrictions.

ZoomSDKErrors.h lines 223–286 enumerates results: Success=0, Failed=1, Uninit=2, ServiceFailed=3, WrongUsage=4, InvalidParameter=5, NoPermission=6, TooFrequentCall=8, PreprocessRawdataError=20, NotJoinAudio=26, among others. These names describe results; they do not authorize retry. The test's result 20 is synthetic, not the observed result of the failed meeting.

## Changes and scope

Native E now carries fixed classifications and numeric result/playback/frame fields, logged as BRIDGE_ERROR. Missing sender/readiness is distinguished from a failed SDK call; -1 means no SDK result. Lifecycle stop and uninitialize callbacks are logged. Python accepts only known classifications and bounded integer fields, supports legacy fixed payloads, and propagates safe details through failure telemetry and run.json. Unknown native data is discarded. Fatal sends are never retried and cannot emit a successful D completion.

Two concrete code defects are addressed: the macOS scheduler compared its next deadline with the time before send, so a stalled send could cause an immediate next call; it now rebases overdue deadlines after send completes. Playback also reserves bridge_playing under play_mutex before removing its pending slot, closing a window where another packet could be accepted during startup. Neither defect is proven to have caused this run: the log shows no stalled send or second packet.

Regression executes the actual native playback loop with a fake sender and no SDK: a 75 ms stall, full and zero-padded partial frames, a two-byte reply, sequential packets, a third-call fatal result, and a missing sender. Restoring only the old cadence in memory makes the stall test fail with exit 11; corrected code passes. Python tests cover S then E, immediate pending-playback failure/cleanup, legacy payloads, malformed or secret-bearing payloads, and safe diagnostics.

## Coordinator handoff

Before another authorized meeting, rebuild the native binary; Python changes alone cannot add the numeric SDK result:

```sh
uv run --frozen python scripts/zoom-sanity.py build --platform macos
bash scripts/zoom.sh
```

Repeat the original short reply, then a longer reply and sequential turns. Check remote audibility on another participant, final syllables, continued human transcription, and task completion. If it fails, collect BRIDGE_ERROR plus run.json.failure; numeric SDK result will distinguish the next investigation. No meeting was started and remote audibility remains unverified.

Verification passed: 33 focused Zoom tests; all 116 tests via `uv run --frozen python -m unittest discover -s tests -v`; `bash scripts/primitive.sh` (two silent mock WAV outputs); `bash scripts/demo.sh` (five mock events, one fixed text reply); `git diff --check`. The native bridge also compiled and linked against the installed Zoom SDK into a temporary binary, without launching or installing it. These checks do not verify live SDK sending or remote audibility.
