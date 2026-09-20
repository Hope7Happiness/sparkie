# Fast semantic wake routing via Devin

Scope: decide whether a finalized human utterance is addressed to Sparkie and
authorizes a reply. This experiment does not classify acoustic speech, change
350ms interruption recovery, join Zoom, or execute meeting tasks. Production
continues using ZoomOutputPolicy; this branch is independent of main.

## Finding

Devin can provide the classifier through its supported ACP CLI. On this machine,
both SWE 1.6 Fast and Gemini 3 Flash Minimal produced valid accept/reject JSON for
all 12 synthetic cases. However, warm requests still took approximately one
second end to end, so the tested path is not a sub-350ms gate. Do not replace the
production synchronous wake rules with this network call yet.

The actual model UID for SWE 1.6 Fast is swe-1-6-fast, as listed by
devin models list. The second tested UID is MODEL_GOOGLE_GEMINI_3_0_FLASH_MINIMAL.
The local list did not include a Flash-Lite model. Model availability depends on
the account; neither the family name nor the word Fast proves routing latency.

## Measured evidence (2026-09-19)

Devin CLI 3000.10.31 (b98cc431), macOS, one persistent ACP process/session per
model, separate from the background task worker. Startup is measured from process
creation through session/new. Decision latency is measured from submitting
session/prompt through its final RPC response, which includes transport and CLI
overhead; it is not model-only inference time or remote audible latency.

| Route | Correct | Decision p50 | Decision p95 | Process/session startup |
| --- | --- | --- | --- | --- |
| Existing local rules | 9/12 | Not measured | Not measured | Not applicable |
| SWE 1.6 Fast via ACP | 12/12 | 1170 ms | 1383 ms | 1317 ms |
| Gemini 3 Flash Minimal via ACP | 12/12 | 1020.5 ms | 1656 ms | 205 ms |

These are a single small, deliberately selected diagnostic set, not an accuracy
benchmark or a latency SLA. Cases run sequentially in a persistent conversation;
prior turns and provider cache state can affect results. Startup comparisons are
also affected by run order. The raw evidence includes time to first text as well
as full decision completion; first text alone is not a validated decision.

The local rules missed sentence-final and indirect addresses and accepted a
product-description sentence. The set also covers ordinary conversation,
quotations, hypotheticals, an unaddressed followup, a command to stop a server,
noise-like text, and an instruction-injection example. Labels are authored test
expectations; no real meeting transcripts or credentials are included.

Raw results: [wake-router-2026-09-19.json](experiments/wake-router-2026-09-19.json).
The full dataset and exact prompt are in
[benchmark_wake_router.py](../scripts/benchmark_wake_router.py).

## Available integration boundary

Local devin acp --help explicitly exposes --agent-type summarizer as a tool-free
agent. The experiment uses that agent with a constrained routing-summary prompt
and strict JSON parsing. It passes no MCP servers, rejects permission requests,
and aborts if tool events unexpectedly appear. Agent thought chunks are ignored.
Devin documents that the summarizer persists summaries to its local data
directory; this is not a stateless inference API. Classification works in this
test, but summarizer is a summary-oriented agent rather than a dedicated stable
classification endpoint. The experiment proves ACP connectivity and feasibility,
not a production service guarantee.

Do not reuse DevinTaskWorker's conversation or lock for routing: a long-running
task would delay every decision, and that worker is deliberately allowed tools.
Use a dedicated, prewarmed, tool-free classifier process if integration proceeds.
OPENAI_API_KEY is removed from the benchmark child environment; Devin uses its
existing login. Only synthetic utterance text is supplied.

## Proposed next integration

1. Begin with shadow evaluation: run the model alongside existing decisions and
   record disagreements without granting new output permissions. Expand the set
   using user-labelled cases before changing production behavior.
2. Keep semantic decisions scoped to session generation, speaker, and final
   utterance ID. Drop stale results after a newer turn, stop, mute, or reset.
3. Keep explicit mute/manual controls and audio interruption local. A binary
   classifier must not turn stop/cancel into permission to speak or affect task
   notification eligibility. Silence remains the default for unaddressed turns.
4. Enforce a bounded decision deadline and strict output validation; malformed
   JSON, tool calls, errors, or stale responses cannot authorize speech. Select
   the timeout fallback explicitly (retain existing rule behavior during rollout).
5. If a sub-350ms decision is required, measure a supported direct inference
   endpoint or another model before rollout. The tested Devin route does not meet
   that budget. No undocumented Devin endpoint is proposed here.

## Reproduce

Offline rules and dataset only (no provider access):

    python scripts/benchmark_wake_router.py

Real requests through existing Devin login, with no meeting joined:

    python scripts/benchmark_wake_router.py --live --output /tmp/sparkie-wake-benchmark.json

The live run uses 12 sequential requests per model. A 10-second per-case timeout
ends testing that model and disposes its process rather than reusing a stuck turn.
CLI stdout/stderr, private provider errors, and reasoning content are not saved;
the result file contains only synthetic classification answers and timing.

## Additional models and direct API comparison

A second sweep on 2026-09-19 used the same 12 cases and prompt. The Devin models
below were confirmed in the current local account catalog. Direct API calls use
the existing OpenAI API key with Responses, store=false, max_output_tokens=32,
no tools, and reasoning effort none for GPT-5.4 nano. Production settings and
the SWE 1.6 Fast background task worker were not changed by this experiment.

| Model / access path | Correct | Full decision p50 | Full decision p95 |
| --- | --- | --- | --- |
| SWE 1.7 Lightning Medium / Devin ACP | 12/12 | 1150.5 ms | 1295 ms |
| GLM 5.3 Flash Low / Devin ACP | 12/12 | 1116.5 ms | 1601 ms |
| Claude Haiku 4.5 / Devin ACP | 12/12 | 1141.5 ms | 2036 ms |
| Gemini 3.5 Flash Minimal / Devin ACP | 12/12 | 974.5 ms | 1331 ms |
| GPT-4.1 nano / direct Responses API | 7/12 | 1150 ms | 2413 ms |
| GPT-5.4 nano / direct Responses API | 11/12 | 725 ms | 1513 ms |

Devin UIDs are swe-1-7-lightning-medium, glm-5-3-flash-low, MODEL_PRIVATE_11
(Haiku), and gemini-3-5-flash-minimal. Neither tested nano model appears in the
current Devin catalog; their availability was verified through actual direct
OpenAI API calls. GPT-5.4 nano is the fastest median measured so far, but its
tail was slower than Gemini 3.5 Flash in this sample. It incorrectly accepted a
quoted wake phrase in a demo script. GPT-4.1 nano missed four actual addresses
and also accepted that quotation. Do not use either result as production
permission to speak without broader evaluation and prompt/error analysis.

The direct requests are stateless; Devin retains the sequence of cases in one
session. The direct client reuses an HTTP connection, but the first call includes
connection setup. This is a practical path comparison, not a controlled isolation
of model inference speed. One pass of 12 examples cannot establish accuracy or
latency guarantees. No tested path demonstrated reliable sub-350ms routing;
changing model names alone has not produced an order-of-magnitude improvement.
For a tighter latency budget, a local classifier is a separate unmeasured option
that needs labelled data and a hardware-specific benchmark.

Official OpenAI sources fetched for this comparison:

- [GPT-5.4 nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano):
  classification is an explicit intended task; reasoning effort none is supported.
- [GPT-4.1 nano](https://developers.openai.com/api/docs/models/gpt-4.1-nano):
  documented as the fastest GPT-4.1 variant, without a reasoning step. That
  relative positioning does not establish end-to-end latency in our environment.
- [Text generation](https://developers.openai.com/api/docs/guides/text):
  supported Responses API entry point.

Raw evidence: [Devin alternatives](experiments/wake-router-alternatives-2026-09-19.json)
and [direct API results](experiments/wake-router-direct-2026-09-19.json).

Reproduce the Devin sweep:

    python scripts/benchmark_wake_router.py --live --models swe-1-7-lightning-medium glm-5-3-flash-low MODEL_PRIVATE_11 gemini-3-5-flash-minimal --output /tmp/sparkie-wake-alternatives.json

Reproduce direct API calls after dependency installation; supply the authorized
environment file path without copying it into this research branch:

    uv run --frozen python scripts/benchmark_wake_direct.py --live --env /path/to/main/.env

Omitting --live performs no network requests. No credentials, real meeting
transcripts, or private provider error bodies are written to results.
