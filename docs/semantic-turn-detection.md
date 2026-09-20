# Semantic completion of Zoom speech turns

Zoom per-participant Realtime sessions now default to
SPARKIE_TURN_DETECTION=semantic_vad. The local main environment is configured for
this mode. Run from the main workspace:

    ZOOM_PLATFORM=macos bash scripts/zoom.sh --language en-US --seconds 180 --response-mode realtime

Each active human participant has a separate Deepgram connection and a separate
Realtime detector using the foreground model (currently gpt-realtime-2.1).
The detector receives real audio resampled from 32kHz to 24kHz. Its configuration
is semantic_vad, eagerness=low, create_response=false, interrupt_response=false,
with no tools. It never generates replies. These extra Realtime connections incur
audio API usage; they do not use the Devin CLI subscription. The existing
SPARKIE_ZOOM_MAX_STT_STREAMS limit also bounds the paired detector streams.

Deepgram still supplies final words and text-confirmed speech starts for fast
interruption. Its 300ms endpoints no longer release individual fragments to the
wake router. Realtime's input_audio_buffer.speech_stopped supplies the semantic
turn boundary. Final Deepgram words are grouped by media timestamps, then the
complete text is passed to Gemini once. Gemini still decides whether Sparkie was
addressed; the background task worker remains SWE 1.6 Fast. Ordinary discussion
is also retained as complete turns in the meeting transcript.

The semantic stop and the final text may arrive in either order. The adapter
waits for Deepgram's finalized audio watermark to cover the boundary and sends
Finalize when necessary. A from_finalize response also acknowledges the audio
frontier at which that request was sent. Words that belong to the next turn stay
buffered. A five-second alignment deadline fails closed rather than authorizing
an incomplete request. Missing word timestamps, provider disconnects and rejected
semantic configuration likewise disable participant input/output authorization
through the existing coverage-gap path. No fallback to 300ms wake decisions is
performed automatically. A stream closed before semantic completion/alignment
logs semantic_turn_discarded and does not invent a final turn.

Turn-specific speech-activity IDs keep newer speech active when an old boundary
arrives late. The existing 350ms false-interruption recovery remains independent
of semantic completion. Self SDK tracks are still excluded before either provider;
this does not eliminate physical speaker echo picked up by a human microphone.

Zoom can stop issuing callbacks during silence. The participant adapter feeds
paced silence to both providers and keeps an inactive stream open for 15 seconds,
rather than closing it after the legacy 1.5 seconds. Both providers see the same
padded media timeline. Diagnostics include semantic_turn_ready (confirmed low
eagerness), semantic_turn_boundary and semantic_turn_discarded, scoped to speaker
and stream. Provider errors are reported as fixed local reason codes.

Set SPARKIE_TURN_DETECTION=deepgram to explicitly restore the legacy endpoint
path. This option applies to Zoom per-participant input; local microphone,
browser and legacy fixed-reply paths retain their previous behavior.

## Validation

On 2026-09-20, the production adapter was exercised through real Deepgram and
Realtime APIs with locally synthesized en-US speech (macOS Samantha, PCM16 mono
32kHz). The phrase was split into two audio pieces with 500ms of silence between:

> Hey Sparkie, could you [500ms pause] check the read me file and tell me how many lines it has?

Realtime confirmed semantic_vad with eagerness=low. Exactly one completed turn
was emitted:

> Hey, Sparkie. Could you check the read me file and tell me how many lines it has?

Measured events relative to test startup: ready at 918ms; semantic boundary at
7249ms (audio_end_ms=5747); final aligned transcript at 7305ms (last word at
4860ms on the media clock). The 56ms boundary-to-text gap demonstrates that the
adapter waited for final transcription. These are synthetic-audio API results,
not Zoom audible latency, a universal turn-completion delay, or human acceptance.
No Zoom meeting was joined for this change; the user is doing the live test.

Offline tests cover short-pause aggregation, late finals, interim revisions,
cross-boundary words, same-speaker overlap, provider failure, timeout, shutdown,
self-track exclusion, sparse callbacks, and one complete Gemini decision/reply.
All 297 Python tests passed, as did scripts/primitive.sh and scripts/demo.sh
(offline simulations; neither establishes Zoom capability).

Suggested Zoom check: pause briefly after "Hey Sparkie, could you", then finish
the request. The wake log should contain one semantic decision for the complete
request. Also test immediate speech interruption, brief-noise recovery and a
completed background task announcement. Low eagerness still makes a probabilistic
decision; it cannot guarantee every human hesitation is interpreted correctly.

Official API configuration reference:
https://developers.openai.com/api/docs/guides/realtime-vad
