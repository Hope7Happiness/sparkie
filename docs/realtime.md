# Realtime voice operation

Browser, local audio and Zoom share RealtimeAgent, TaskCenter and the artifact workspace. Realtime handles foreground conversation; Deepgram transcribes humans; Devin or Codex executes background tasks.

## Run

Run these in separate terminals:

~~~bash
uv run --frozen sparkie workspace --host 0.0.0.0 --port 8790 --worker devin
npm --prefix frontend run dev
~~~

Open http://localhost:5178/. Start a new conversation to load prompt changes. The page supports manual stop, microphone mute/recovery, interruption, task cancellation and result announcements. Browser microphone access needs localhost or trusted HTTPS.

For native local audio:

~~~bash
bash scripts/local.sh --language en-US --seconds 120 --echo-mode headphones
~~~

For Zoom, [build the bridge](zoom-macos.md), keep the workspace and frontend running, then:

~~~bash
ZOOM_PLATFORM=macos bash scripts/zoom.sh --language en-US --seconds 3600
~~~

SPARKIE_TASK_BACKEND selects devin or codex. Devin defaults to swe-1-6-fast and reuses one process/conversation per voice session. Tasks are serial; foreground conversation continues. Running Devin tasks accept revisions through update_task; prior external effects are not rolled back. Other backends may reject updates after execution starts. Ending the session terminates pending work.

## Identity and replies

Sparkie is an AI meeting teammate that helps turn discussion into completed work. Simple introductions are answered directly. Self-reports are delegated with a short artifact title and explicit public facts about Sparkie, its role, capabilities and limits; the worker does not receive the Realtime system prompt.

Zoom follows application wake/output policy. Browser/local is a direct conversation without a wake word and does not claim to be connected to Zoom. Sparkie knows only supplied audio, transcripts, context and tool results; it cannot implicitly see cameras, screens or private meetings.

The prompt requests one or two short sentences for ordinary replies, one for delegation and at most three for results, with the main finding first. Details belong in the task panel. These are model instructions, not a hard sentence limit.

For a clear objective with uncertain words, Sparkie delegates known facts and asks the worker to consult the finalized transcript. It does not invent names, locations or alternatives. Transcripts may lag or contain errors; unresolved essential details require clarification.

## Artifacts

Workers generate content; Realtime chooses presentation through list_artifacts, present_artifact and hide_artifact. It may proactively show relevant reports, preserve the report under discussion and return to the board without deleting files or cancelling work. The catalog supplies metadata, not complete documents.

The voice page embeds the workspace board. Queued/running tasks show a short name and generation indicator, not streamed document content or a completion percentage. Markdown renders the actual file body without summary wrappers. Supported raster images are snapshotted and downloadable.

macOS Zoom shares the full /workspace.html page in the native WebView. Frontend and backend must both be running. Present selects a report; hide/Back/Esc returns to the board. App-window sharing fallback needs screen-recording permission; host sharing policy also applies. Selection acknowledgement does not prove remote visibility.

## Interruption

Browser/local uses server VAD. macOS participant mode uses final participant text as foreground input and listens during playback. Confirmed human speech cancels generation/playback; a brief noise candidate pauses future packets for a bounded confirmation window. False alarms resume retained audio; confirmed interruption never resumes old PCM.

Background work survives interruptions. Task results remain pending/offered until trusted explicit human confirmation; generation and SDK submission do not establish delivery. Eligible responses can regenerate interrupted announcements. Explicit stop/mute pauses automatic announcements.

Zoom semantic completion groups Deepgram text using Realtime boundaries. The optional Devin wake router sees eight preceding conversation entries. See [semantic turns](semantic-turn-detection.md) and [contracts](interfaces.md). Participant failures record gaps and disable automatic output rather than silently accepting incomplete context.

## Validation

Run the root README checks. Live acceptance should cover questions, real file tasks, follow-up edits, cancellation, natural interruption, unrelated task completion during report review and return to the board. In Zoom, verify audio and shared content from another participant device.

The 2026-09-20 identity test used actual gpt-realtime-2.1 text input and Devin swe-1-6-fast. Sparkie introduced itself without delegation, passed identity facts into a named report request and generated Markdown identical to artifact.content.markdown. It checked task status before reporting completion. Local evidence: output/identity-verification/20260920T093827-05053a/. This was not microphone, Deepgram, browser-rendering or Zoom acceptance. Introductions varied between two and three sentences.

Official references: [Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations) and [VAD](https://developers.openai.com/api/docs/guides/realtime-vad).
