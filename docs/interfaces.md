# Interface contracts

## Identity and session mode

Browser, local and Zoom sessions share the Sparkie AI meeting-teammate identity. Session instructions distinguish Zoom participation from direct conversation. Simple introductions are answered directly; self-reports use delegate_task(request, artifact_title) with explicit public identity/capability/limitation facts because the worker does not receive the foreground system prompt.

## Audio and transcripts

AudioFrame carries sequence, signed little-endian mono PCM16, sample_rate, optional capture-time gated state, speaker_id and timestamp_ms. The Zoom bridge uses 32 kHz audio; Realtime transports use 24 kHz. RealtimeAudioTransport.append_output queues audio without waiting for playback and retains per-item playback records for interruption. Queue sizes and playback are bounded; failures are explicit.

TranscriptEvent contains meeting_id, event_id, timestamp_ms, text, optional speaker/speaker_id, is_final and source=human|bot. SpeechActivity carries candidate|started|stopped, timestamp_ms, speaker_id and stream_id. Generated bot transcripts are not evidence that playback was heard.

macOS dual-input-v1 publishes mixed A frames, participant U frames and metadata. U frames exclude the SDK self-track; ParticipantEars filters self again and opens bounded per-speaker recognition streams. Shared microphones are not precise human diarization, and another participant microphone can recapture bot audio.

In participant mode, final human text is authoritative foreground input, including ordinary discussion and speech during playback. Mixed A input preserves capture timing but is zero-filled before reaching Realtime, avoiding duplicate acoustic/text turns. The model does not independently hear the original participant audio in this mode. Browser/local and Linux use their configured mixed-audio transport.

Deepgram speech events and final transcripts share an ordered bounded queue. SpeechStarted produces a candidate; the first nonempty interim/final text confirms started. A candidate pauses future playback packets for 350 ms without cancelling generation or discarding buffered audio. Already-submitted packets finish. Repeated candidates do not extend the window. Unconfirmed noise resumes retained audio; confirmed speech cancels output through cancel-v1 and semantic truncation. Late confirmed speech still interrupts. Finalization/end releases speaker state and duplicate results cannot retrigger interruption.

Participant failure records a coverage gap, stops automatic output and preserves the Realtime connection/background work; it does not silently fall back to mixed input. Normal recovery requires a new session, while trusted human text control remains available. Diagnostic event times measure application receipt, not remote audibility.

## Browser and two-speaker transport

Browser audio uses same-origin /audio with a session ID and validated Origin/Host. AudioWorklet captures PCM16 mono 24 kHz in 20 ms packets and renders queued output. Browser heartbeat leases the session. Manual-stop mode accepts seconds=0. A stalled microphone leaves background work running and exposes recovery; stopping closes media resources.

The separate /multitrack.html transcription lab uses one physical microphone with two mutually exclusive speaker buttons. Its /multitrack-audio protocol sends 2–4 synchronized 32 kHz tracks (two in the UI), sequence times 20 ms, 1280 bytes per track. Non-selected tracks contain zeros. Capture epochs discard stale frames across identity switches. It uses live Deepgram with production participant decoding, without Zoom, Realtime or task workers. See [lab operation](multitrack-lab.md).

## Tasks and tools

Realtime exposes delegate_task, update_task, task_status, cancel_task, remain_silent, list_artifacts, present_artifact and hide_artifact. Work requiring research, current information, files, code or other external tools is delegated. File creation and browser opening have no foreground shortcuts.

TaskCenter persists request, artifact_title, transcript snapshot, worker progress, queued/running/completed/failed/cancelled status and verified result. Tasks serialize through one worker while voice stays responsive. Devin retains one ACP process/conversation per voice session; queued updates replace the request, and running updates interrupt/continue that task asynchronously. Cancellation does not roll back external effects. Codex runs with configured CLI settings and login. Neither backend uses the foreground OpenAI key for CLI billing.

Workers receive the finalized transcript snapshot available at delegation and explicit request details; later speech is not silently added. Background completion/failure creates a notification for the foreground to consider. Session end cancels unfinished work. File materialization and presentation contracts follow below.

### Semantic interruption and trusted human controls

Interruption cancels the active response and any response.create already in flight, stops **all** transport outputs through the existing cancel-v1 barrier, discards pending PCM/resampler state, and truncates every incomplete assistant audio item at the transport's conservative progress estimate. Late chunks for cancelled responses, including previously unseen items, cannot restart playback. Cancelled items are truncated once. Generated transcript fragments are retained as explicitly unconfirmed draft context, separate from heard conversation; verified task results remain the source of truth. No native protocol changes are required.

The application now owns response creation: server VAD still detects speech and cancels generation, but create_response=false. Speech-start cancels playback; speech-stop alone does not regenerate. The subsequent input_audio_buffer.committed event makes the user audio turn available. Fresh response creation waits for any cancelled response to finish, injects pending semantics, and generates new audio. The same ordering applies to an externally committed text turn. A terminal interrupt with no subsequent turn deliberately stays silent; it never resumes old PCM.

TaskCenter persists an announcement object in tasks.json, independent of job execution status:

- pending: completion/failure awaiting a response opportunity, ordered by completion.
- offered: result supplied to Realtime for an attempt; generation, queueing, rendering and SDK submission do **not** confirm delivery.
- confirmed: a trusted explicit human acknowledgement of that task and attempt. Confirmed results are excluded from automatic recovery and the model receives a do-not-repeat update. A user can still explicitly request a result again.

Interrupting an in-flight announcement or one with unfinished playback returns its unconfirmed tasks to pending in original order. Repeated interruptions deduplicate obligations. Tool continuations retain their associated announcements. Results offered in an uninterrupted, fully submitted reply remain offered/unconfirmed: ordinary later speech does not automatically repeat them. remain_silent likewise leaves results available without an automatic notification loop. Pending results are explicitly supplied for reconsideration after the new user turn; fresh wording and whether to defer depend on that turn. This is delivery uncertainty, not a claim of audibility. Tasks and announcement states persist for inspection; automatic cross-session recovery remains unsupported.

background_notification_offered replaces the misleading background_notification_delivered event and includes announcements [{task_id, attempt}] plus delivery_confirmed=false. background_notification_confirmed is emitted only on explicit human confirmation. Attempt IDs reject stale confirmations after retry. Cancellation, native errors and truncation diagnostics remain intact.

Trusted stdin JSON controls (also callable as RealtimeAgent.control from a local integration):

~~~json
{"action":"interrupt"}
{"action":"human_turn","source":"human","turn_id":"human-42","phase":"start"}
{"action":"human_turn","source":"human","turn_id":"human-42","phase":"commit","text":"Stop; just give me the conclusion."}
{"action":"confirm_delivery","source":"human","task_id":"<task-id>","attempt":1}
~~~

human_turn start stops playback immediately, before provider cancellation/truncation messages. A matching commit supplies authoritative final human text (nonempty, at most 8000 characters), records it in the transcript ledger and requests fresh generation. IDs are unique per session, 1–128 characters; duplicate starts/commits are idempotent. Only one external turn may be open; another start or unmatched commit is rejected. source=bot or missing source is rejected. These labels are a trusted caller contract, **not speaker identification or authentication**. The teammate's separator must exclude Sparkie's output before calling this boundary; this module performs no separation, diarization, VAD or STT on separate streams.

The first human_turn start selects external-text input for the remainder of that session. Mixed microphone frames sent to Realtime become equal-length silence, and mixed VAD commits are removed/ignored, including delayed events, so a turn cannot appear through two input paths. All subsequent conversational turns must use start/commit controls; restart the session to return to mixed audio input. Deepgram's existing capture/transcription path and capture-time Zoom echo gate are unchanged; externally committed text is separately recorded as source=human. The legacy interrupt control alone does not select external-text mode and can still be followed by a normal microphone turn once the echo tail expires.

Zoom speaker mode still cannot acoustically hear an interruption through its gated mixed input. The external signal can stop playback immediately when received; already submitted SDK/network/device audio cannot be recalled, and cancel-v1 acknowledgement does not establish the remote stop instant. Real meeting testing must verify acoustic stop latency, response sequencing and natural semantic recovery. No remote audibility or full-duplex capability is claimed by offline tests.

Interruption review refinements: public response requests acquire the same turn lock as controls, provider events and notifications; internal transitions use a separate lock-held helper (no recursive lock acquisition). Announcement deferral matches both task_id and attempt, including explicit report_task retries and send failures. Completion during a semantics send remains independently pending. Duplicate response-created/done and microphone-start/commit events cannot consume newer state. An overlap error restores pending obligations and waits for the existing response before retrying. An unsolicited cancellation clears queued playback even if its speech-start event has not arrived yet.

Cancelled audio cleanup records the provider content_index and also tracks audio-transcript parts with no PCM delta. Late final transcripts update draft context; identical final/delta replays do not enqueue already supplied text again. Only audio content is truncated; committed mixed-input items are deleted once; cancelled function calls receive one explicit non-executed output without running tools. Local playback progress freezes at cancellation while queued PCM is reclaimed. Simple injected task stubs remain usable: notification obligations are retained in memory when persistence methods are absent, and unsupported delivery confirmations are rejected rather than crashing. These protocol paths are tested offline; provider acceptance and remote playout timing still require live validation.

### Zoom output mute MVP (supersedes automatic replies for all Zoom turns)

Zoom final-transcript matching also checks explicit sentence starts within an aggregated final segment: after 。！？!? or a period followed by whitespace/end. Only the observed compact greeting helloSparkie/helloSparky (case-insensitive, with the existing exact name boundary) gains a missing space before applying wake.py rules. Commas, mid-sentence name mentions and speculative transliterations do not become wakes. The last explicit addressed wake/cancel in a segment wins; an unaddressed cancel is recognized only at the original segment start. The selected addressed suffix is supplied as the fresh request; preceding discussion remains in the live audio context. This normalization is Zoom-only; shared wake.py and browser/local behavior are unchanged.

Diagnostics: zoom_wake_decision contains fixed decision/reason, sentence_index and compact_greeting_normalized, never transcript text. zoom_response_not_requested distinguishes wake_rejected, explicit_mute, output_muted and waiting_for_turn_or_response (with state booleans). zoom_response_requested is emitted after response.create is sent; it is not provider acceptance or audibility. Existing realtime_response_started and zoom_output_suppressed distinguish provider response creation and rejected PCM. Duplicate final transcripts still cannot request twice.

Zoom Realtime sessions install a local ZoomOutputPolicy and begin output-muted. This is Python output routing, not Zoom platform microphone toggling or input mute. PCM input, Deepgram, the same foreground Realtime connection/conversation and Codex jobs continue. No reconnection/context rebuild occurs on wake. Browser/local sessions do not install this policy and retain their existing behavior.

create_response remains false. While output-muted, ordinary committed audio stays in the Realtime conversation but does not request an assistant response. This avoids creating unheard assistant answers without losing incoming meeting context. Deepgram final human transcripts apply the exact existing wake.py sentence-start Sparkie/Sparky rules (optional Hi/Hey/Hello, existing ASR special case); partial/bot/duplicate records cannot open output. Cancellation uses existing CANCEL rules, with or without a leading address; no model classifier or new fuzzy phrases. The addressed final text is additionally inserted as the explicit request before response.create because the two providers do not share turn IDs. That can duplicate the textual representation of already heard audio, but never creates a second response from the audio commit. ASR segmentation/latency and sentence-start product-name false wakes retain their existing limitations.

Zoom mixed-input VAD no longer automatically interrupts responses (interrupt_response=false, Zoom only), preventing late events for the same utterance from cancelling its newly authorized answer. Final cancellation text, terminal controls and trusted human_turn/start still cancel. A different qualifying addressed final transcript supersedes the previous chain. Unrelated speech does not authorize another response or extend output permission. Deepgram failure therefore disables automatic transcript wake; the live Realtime input continues, and manual unmute plus trusted human_turn controls remain available.

The output permit belongs to a response chain, including its legitimate tool continuations and all queued items. It closes only after the terminal response.done and queue drain/cancellation. Late or unsolicited responses cannot reuse a permit: unowned audio is suppressed before resampling/enqueue, tracked as unheard draft content and truncated through existing semantic-interruption mechanisms. The transport independently checks item ownership. zoom_output_state / zoom_output_control / zoom_output_suppressed are concise diagnostics, never remote-audibility evidence.

There is no product speech-duration limit and Zoom's former per-item 120-second generation limit is removed. The aggregate bounded pending-PCM capacity remains 120 seconds (7,680,000 bytes including the unacknowledged in-flight packet); it is a backlog safety limit, not a maximum total reply duration. Overflow still fails explicitly/cancels rather than dropping audio or growing unbounded. Long replies drain normally while generation continues. Configured overall session expiry also remains in force.

Tasks created by an authorized response chain (delegate_task) receive zoom_output_origin=addressed_turn in tasks.json and an in-session eligibility record. Only their pending notification attempts may open output at the existing idle opportunity; unrelated task completions remain pending/visible and cannot open output or be automatically mixed into offered semantics. Mute/interruption returns affected offers to pending without cancelling jobs or marking them delivered. Confirmed states remain unchanged. Automatic reannouncement pauses only after explicit dismissal/manual mute until a new wake; ordinary participant interruption remains pending and is retried when quiet; pending information is reconsidered on that new chain or an explicit eligible report_task. Eligibility is not restored as an output permit after restart.

Trusted controls: {"action":"mute"} immediately revokes the current chain and stops/clears all queued audio through semantic interruption and cancel-v1; jobs and input continue. {"action":"unmute"} also clears/revokes any stale chain and arms the **next final human turn**, even without a wake name; it does not replay PCM, immediately speak, or enable all future turns. A wake name can reopen output after mute; mute is not a permanent hard lock. In external-human mode, final human_turn text uses the same rules; start still stops current playback. Speaker separation is not implemented. Existing external-text input selection remains an independent input mode, never a consequence of mute/unmute.

Restart/new sessions always start output-muted with no restored chain. There is currently no automatic reconnect in RealtimeAgent; a replacement session must construct a fresh policy. Zoom's existing speaker echo gate still hides mixed human speech during audible playback plus its tail; acoustic stop phrases in that window require the separated-human control producer. Native protocol/build is unchanged, and already submitted remote audio cannot be recalled.

### Bounded Zoom join and macOS native startup diagnostics

Python owns an absolute join_timeout (default 120 seconds), now covering launch, bridge handshake and audio/microphone readiness. A watchdog observes startup even when the bridge handshake itself blocks. No automatic join retry is performed. Success still requires both received audio and microphone readiness, not JOIN_REQUEST result=0 or AudioReady alone.

The macOS receiver joins muted, installs the external microphone, then requests unmute, restoring the pre-multitrack startup sequence. An already-unmuted SDK state is not proof that the external source received onMicStartSend. There is no automatic re-unmute loop. Until join succeeds, both A and U input frames are discarded before entering their consumer queues; zoom_startup_audio_discarded explicitly marks this startup coverage gap and audio diagnostics count startup_frames_discarded. Participant metadata and readiness/control packets continue to be processed. Startup speech cannot trigger an unplayable reply, and a missing mic callback reaches the existing bounded audio_readiness_timeout instead of QueueFull. Speak only after listening_ready; after that, normal bounded queues and overflow failures remain unchanged.

The installed macOS receiver already writes fixed startup/status records to its private sdk.log. Python incrementally reads only full allowlisted records (bounded reads and line buffers); no SDK rebuild or protocol change is needed. zoom_join_progress preserves native_stage/sdk_result and, when available, meeting_state, meeting_state_name, meeting_error, meeting_end_reason, state_observed_ms plus fixed actionable hints. Raw SDK lines, arbitrary error text, config values and credentials are never copied into events/run.json. These are macOS SDK 7.1.5 enum values; 1/101 is Connecting/no error, not an immediate failure. State 2 is WaitingForHost and 10 is InWaitingRoom.

At the overall deadline zoom_join_failed distinguishes connecting_timeout, waiting_for_host_timeout, waiting_room_timeout, audio_readiness_timeout, reconnecting_timeout or join_timeout. Explicit native failed/ended/auth/join-request failure records fail promptly with their numeric evidence. session_failed and run.json.failure retain those fields. The original deadline never resets on repeated states or admission transitions; an admission timeout means the host action did not complete within the configured budget, not that Zoom reported a network failure.

Failed/cancelled join cancels its handshake task and reader, closes its bridge, and tears down only its owned child/container before returning. macOS attempts SIGTERM (10 seconds), then kills its owned child if necessary (5-second wait); zoom_receiver_forced_stop records that fallback. Repeated session cleanup is safe. The native standalone probe is outside this Python voice-session watchdog. Output mute and semantic interruption are unchanged.
## Meeting workspace

WorkspaceStore uses SQLite. External meeting keys (external_kind, external_id) resolve to an internal ws_ workspace_id. Tables hold meetings, transcript_events, tasks, artifacts and meeting_state. Platform adapters remain separate from the store and event vocabulary.

EventBus adds workspace_id and increasing seq. Subscriber queues are bounded (default 256); overflowing subscribers are disconnected instead of silently dropping state. HTTP serves snapshots and metadata; writes use the event WebSocket:

- GET /healthz
- GET /api/meetings/resolve?kind=...&external_id=... (optional reset=1)
- GET /api/workspaces and /api/workspaces/<id>
- GET /api/artifacts/<id>
- WS /workspaces/<id>/events?generation=<n>

Socket messages include utterance, end_meeting, cancel_task, task_update and artifact.control. Live mirrored utterances carry live=true and never invoke the standalone keyword router. TaskCenter owns mirrored task IDs and lifecycle; the workspace broadcasts task.updated and artifact.ready. Cancel events return to the live session and cancel its actual worker task.

Standalone workspace utterances use heuristic IGNORE/RESPOND/CREATE_TASK/PRESENT_ARTIFACT routing. RESPOND emits an event, not synthesized speech. The configured worker creates real artifacts; --worker demo returns explicitly simulated artifacts for isolated tests. Live Realtime controls its own tasks and presentation. An ended live session can generate a summary without automatically replacing its selected artifact.

WorkspaceClient mirrors transcripts and task updates from all Realtime transports. Connection failures disable mirroring without stopping voice. A new session resolves with reset=1; a reused Zoom meeting number gets a new generation rather than old task output. The server has permissive CORS and no user authentication; it is local development infrastructure, not a public multi-tenant service.

### Zoom shares the full workspace

macOS Zoom loads /workspace.html?workspace_id=<id>&server=<backend> from the running frontend at SPARKIE_WEB_PORT (default 5178). The workspace backend uses SPARKIE_WORKSPACE_SERVER (default 127.0.0.1:8790). Start backend, frontend, then Zoom. Restart services after code updates.

The workspace_id entry fetches the existing snapshot and subscribes to its generation without creating/resetting a meeting. Transcript, tasks, catalog, stage and fullscreen stay available. The meeting query entry and the browser embedded workspace entry remain supported. Sharing is requested only if workspace mirroring connected; zoom_share_requested means the URL was sent, not that viewers rendered it.

Returning to the board uses hide_artifact and artifact.cleared: close fullscreen, preserve tasks/catalog and keep Zoom sharing. If new content is also requested, clear presentation before delegating only the new content. Back/Esc invalidates pending fullscreen fetches so an older request cannot reopen a closed view.

### Workspace session generation and reset isolation

The meetings table now has a persistent integer generation (existing databases migrate to 0). Reset atomically clears the session tables and increments generation, cancels only that workspace's runtime jobs, and publishes workspace.reset with the new generation. Jobs capture generation before scheduling and check it before reading context, publishing errors, or storing results; even a worker that returns after cancellation cannot repopulate the new session. Cancellation does not undo external work already performed.

Resolve responses and snapshots expose workspace.generation. Clients connect to /workspaces/<id>/events?generation=<n>; a stale resolve-to-connect attempt closes with 4409. Writes carry generation and are ignored when stale; legacy sockets without this field stay bound to their connection generation. A live WorkspaceClient keeps its original generation and disables mirroring after a reset, including old end_meeting messages. Browsers adopt the new snapshot generation for subsequent cancel/utterance requests. Snapshots include the bus seq at read time; during reset refresh the browser buffers events and only replays events newer than that snapshot. Reset also invalidates old artifact fetches, hydration cache and active selection. This is session isolation, not authentication.

### Zoom microphone mute versus playback failure

Only ZoomMicrophoneMuted (the explicit N signal or a pre-send readiness check) is retried. Playback timeouts, malformed PCM and transport failures propagate as failures. PCM stays in the bounded buffer until a complete SDK packet acknowledgement; mute retains that packet, waits for microphone readiness, then retries after the existing native cancellation acknowledgement. Since partial packet progress is unknown, a mid-packet mute may repeat up to 100ms on recovery, but does not silently skip audio or report a dropped packet as played. A confirmed human interrupt or manual stop still cancels retained audio. Startup continues discarding input while _joining; post-join queued audio is drained without a startup flush.

### Optional semantic Zoom wake router

RealtimeAgent accepts an optional wake_router with async start(),
classify(text, *, context=(), speaker=None, speaker_id=None)
and close(), plus model for diagnostics. classify returns accept or reject; only
the agent/output policy can authorize speech. SPARKIE_WAKE_ROUTER=devin selects
the dedicated tool-free Devin adapter with SPARKIE_WAKE_MODEL (default
gemini-3-5-flash-minimal). Unset/rules preserves the existing local policy. This
setting affects Zoom Realtime only and is independent of DEVIN_MODEL for tasks.

In devin mode this supersedes the historical explicit-name requirement above:
the current utterance is judged semantically against the previous eight human /
assistant entries (oldest first), excluding current itself. Contextual follow-ups,
corrections and answers to Sparkie's questions can authorize a reply without its
name. Human-to-human discussion, third-person mentions and acknowledgments needing
no answer should stay silent; uncertain recipients should be rejected. Names are
neither required nor sufficient. The rules mode retains its original behavior.

The session-local deque includes rejected human discussion and available speaker
name/ID. Only deduplicated final human turns enter it; assistant transcript deltas
update one entry per output item, preserving initial arrival order. Each routing
request gets a copied snapshot. Assistant text is labelled generated, not verified
audible: interruption removes unplayed items and marks partially submitted items
as potentially containing unheard words. Cancelled late output cannot restore an
entry. This is a bounded routing window, not meeting memory or acoustic diarization.
New meetings start empty; transport resets do not erase the application's window.
The adapter reuses its warm process but creates a fresh ACP session per decision,
so previous routing prompts do not expand the explicit eight-entry window.

Final human text still enters meeting context once. Semantic classification runs
outside turn_lock and consumes the full final utterance. A monotonically
increasing local version fences acceptance against new speech, a newer final,
manual controls, input failure and shutdown. Old provider-output cancellation
does not invalidate a newer human decision. Explicit dismissal/manual-next controls
stay local; raw speech candidates and the 350ms recovery do not wait on the model.
Routing errors/2.5s deadlines fail silent for that utterance. Eligible task
notifications are deferred only while a decision is pending, then use existing
quiet/authorization rules. No task-worker conversation or lock is reused.

Diagnostics: zoom_wake_router_config (context_entries limit), zoom_wake_router_ready/unavailable,
zoom_wake_routing (actual context_entries count), zoom_wake_router_failed (error_type, action, latency_ms when
available), zoom_wake_decision (semantic_router/local_control), and
zoom_wake_decision_discarded for late returns. Provider response bodies and
thoughts are not logged. See fast-wake-router-research.md for live-call evidence
and the remaining user-run Zoom validation.

### Semantic completion before Zoom wake routing

Zoom per-participant sessions default to SPARKIE_TURN_DETECTION=semantic_vad
(legacy deepgram is explicitly selectable). SemanticTurnEars pairs Deepgram
finalized word timestamps with a separate Realtime semantic_vad/medium detector for
each non-self participant. Both receive the same padded audio timeline. Only an
aligned complete turn becomes TranscriptEvent; Deepgram speech_final fragments
no longer call human_transcript individually in this mode. Fast text-confirmed
SpeechActivity.started still interrupts immediately, independently of completion.

SpeechActivity.stream_id may contain an adapter-local turn suffix. ParticipantEars
prefixes it with the participant and provider-stream serial instead of replacing
it, and tracks each active suffix separately. This prevents a late old stopped
event from clearing a new turn by the same speaker. Unsuffixed adapters keep their
existing IDs. Semantic mode supplies paced silence when callbacks stop and closes
idle provider streams after 15s; legacy mode keeps its previous 1.5s policy.

Alignment uses finalized result coverage or the audio frontier acknowledged by a
Deepgram Finalize response. A pending boundary times out after 5s. Detector or
alignment failure uses participant_input_failed and a semantic_turn_unavailable
coverage gap, without falling back to fragmented wake requests. Actual API
configuration, usage implications and validation are in semantic-turn-detection.md.

### Browser voice artifact board

The non-Zoom voice page at / embeds the existing workspace renderer in artifact-only mode. SessionController retains workspace_linked.workspace_id as workspaceId in /api/status independently of the bounded event history; it remains available after normal session end and is cleared on a new session. The page binds the iframe once per workspace, restores it on refresh, and clears the previous board while the next session connects. Voice controls and background-task cancellation/reporting remain in the parent page.

/workspace.html?workspace=<id>&server=/workspace-api&embedded=1 opens an existing workspace directly, without resolving a Zoom meeting or resetting it. Completed artifacts populate the catalog without changing presentation. Embedded mode restores only the explicitly selected artifact from the snapshot. Standalone navigation retains the full workspace view. The Vite /workspace-api HTTP/WebSocket proxy targets SPARKIE_WORKSPACE_SERVER (default 127.0.0.1:8790), so LAN clients use the same origin instead of connecting to their own localhost. Snapshot refresh after WebSocket subscription catches artifacts produced during initial connection. Workspace outages do not stop voice sessions; results remain in the original task list, and the board reports its connection state.


### Realtime artifact presentation controls and generation status

Devin/background workers produce content; Realtime owns presentation for live sessions. Realtime has list_artifacts, present_artifact(artifact_id), and hide_artifact tools through the injected WorkspaceClient. The catalog returns up to 50 recent metadata records (including task_id, title and status), not whole documents. Show/switch targets an actual ready artifact in the same workspace. Hide clears the shared active_artifact_id without deleting artifacts or cancelling jobs. Existing interrupted-response guards also fence these tool calls.

The workspace socket accepts artifact.control with action=list|present|clear, request_id, generation, and optional artifact_id. It returns artifact.control.result to the requester. Present persists selection and broadcasts artifact.present; clear broadcasts artifact.cleared. Invalid, unavailable, cross-workspace and stale-generation requests return explicit errors. Client requests use the existing two-second deadline; timeout means unknown outcome, never success. An acknowledgement proves server selection, not that every browser rendered it. Manual board selection uses this same server path. Live transcript mirroring no longer applies keyword-based presentation; standalone/demo routing retains its existing behavior. Live-session end reports still generate but do not automatically replace the selected document after Realtime disconnects.

The board shows separate generation cards for queued/running tasks, with document shimmer animation while running and static waiting state while queued. Completion, failure, cancellation and reset remove the associated card; other in-progress tasks and the selected document remain visible. The animation indicates task activity, not incremental document contents or a measured completion percentage. Reduced-motion preferences disable motion.

Realtime's presentation prompt now makes the decision context-dependent on user
turns and task-result notifications: proactively present a ready report when it
supports the current explanation/review or the user is waiting for it. Match task
ID, title and summary, including older reports; keep the current selection for
unrelated completions and avoid re-presenting an already selected report. Simple
answers/status acknowledgements need no board change. Respect voice-only/clear
requests and clarify only when context and catalog leave equally plausible
reports. Catalog metadata does not imply access to the complete report body.
These are model instructions, not a deterministic automatic selection policy.
They apply when the next Realtime session starts; an existing connection retains
its previous instructions. Reference: https://developers.openai.com/api/docs/guides/realtime-conversations .


### Worker document content versus completion summary

This extends the earlier summary-only task_update contract. For a generated Markdown
file or raster image, Devin and Codex workers declare their primary deliverable in one fenced
sparkie-artifact block containing JSON with a path field. The shared task_artifacts
processor strips the declaration from the completion summary and snapshots the
UTF-8 file on the worker host before completion is emitted. Ordinary prose paths
and incoming workspace socket messages never trigger local file reads.

The file must resolve inside the worker workspace or the user's Desktop and be a
regular file. Markdown (.md/.markdown) must be nonempty UTF-8 and fit in 128 KiB.
Raster images (.png/.jpg/.jpeg/.webp/.gif) must fit in 2 MiB and their file signatures
must match their declared extension; SVG/HTML are not image deliverables. Images
are snapshotted as data URLs in content.image, with the original filename for
download. The workspace socket accepts up to 4 MiB per message to carry base64
images; the voice console/event stream carries metadata only, keeping media out of
its bounded audio/control pipe. Full snapshots remain in tasks.json and artifacts.
Symlinks resolving outside those roots are rejected. One primary deliverable is
supported per task. Reading happens off the voice event loop. This is an explicit
worker output contract, not automatic discovery of files changed by shell tools;
workers must emit the declaration for file deliverables.

background_task/task_update now optionally carries artifact={type,content:{markdown}
or {image,filename},source_path}. The workspace stores that content while the task
result stays the concise completion summary. Task status
and spoken-result notifications include only source_path metadata, not the full
document. Inline text answers without a declaration keep their existing rendering.
An invalid/unreadable declared document produces artifact_error, shown in the task
panel, and no misleading summary artifact; it does not undo the completed task.
Standalone workspace workers use the same materializer. Artifact creation does
not change the active presentation; Realtime/manual selection still owns that.

Regression coverage exercises file creation through TaskCenter and AgentRuntime,
exact document snapshots, title extraction, concise voice notifications, preserved
selection, duplicate completion, and invalid/out-of-scope files. Browser inspection
of the reported existing artifact verified the actual Markdown heading, sections
and table after repairing its stored content. This is document pipeline validation,
not new live-model or Zoom acceptance.


### Artifact names and direct previews

Realtime delegate_task now requires artifact_title, a short user-facing name
(1–80 characters) chosen before delegation. Execution details stay in request.
TaskCenter persists and emits the name from queued onward; the workspace migrates
existing task tables with a nullable artifact_title column. Both waiting cards and
task lists show this name, including after refresh, and use a neutral Task output
fallback for older unnamed tasks instead of exposing execution prompts. The final
artifact keeps the supplied name in its catalog; older tasks derive one from their
content. This does not select or auto-present an artifact.

Markdown stage/fullscreen views render the document itself, without another title
and summary wrapped around it; catalog cards retain metadata. Markdown downloads
also preserve the original body. Image downloads export the image itself.
The latest Boston test reproduced duplicate preview metadata and the PNG rejection
unsupported_document_type. Regression coverage includes naming through the Realtime
tool before the worker runs, title persistence, legacy database migration, a media
payload above the former 1 MiB socket limit, exact Markdown exports and wrapper-free
previews. Browser verification of the reported test confirmed one Markdown title
in both previews, and byte-for-byte delivery and actual decoding of its existing
1334 × 1050 PNG. An isolated synthetic task exercised named waiting cards over
real HTTP/WebSocket and refresh; no new model or Zoom acceptance was performed.

### Zoom Realtime artifact sharing

macOS Zoom Realtime uses the same TaskCenter, artifact_title field, file/image
materializer and Realtime presentation tools as browser voice. Once the bridge is
ready and WorkspaceClient is connected, the session sends the V bridge command
with the full frontend /workspace.html?workspace_id=<id>&server=<backend> URL.
This uses the running Vite frontend (SPARKIE_WEB_PORT, default 5178), using the same renderer as browser voice. The native receiver snapshots its WKWebView and
sends 1280×720 I420 frames through the SDK external share source at up to 4 fps.
Only one snapshot may be pending; frames for a replaced sender or shutdown are
discarded. Premultiplied bitmap rendering prevents the previously observed black
frames. If the external source is unavailable, the existing app-window path is
retained with a screen-capture permission check. V status 5 is
screen_permission_missing. Linux receivers do not implement this sharing path.

The workspace page follows explicit artifact.present/artifact.cleared and
snapshot.state.active_artifact_id, never the newest artifact automatically. It
renders Markdown without repeated metadata, shows raster images, and displays
short names and activity for queued/running tasks. Reconnect restores the current
selection and task names; reset clears them. Selection revisions fence late
artifact fetches, and snapshot seq fences buffered socket events. Reduced-motion
preferences disable the generation animation. Existing Zoom wake and interrupted
response guards also apply to the presentation tools.

Validate sharing and audio on a second participant device; local bridge tests and compilation do not establish remote visibility or audibility.
