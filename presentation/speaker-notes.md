# Sparkie — speaker notes

Order: motivation → competitive context → product and video → architecture → limitations and outlook.

The Gemini participation router is the central technical page. Timing is a speaking guide, not a performance claim. The YouTube player does not trim the video.

Use Right/Left to move through items, Page Down/Page Up to change slides, and P for the synchronized speaker view.

## 01 — A teammate with the meeting context.

We want an agent that is already part of the meeting. It follows the discussion, understands what a request refers to, and can handle work while the team keeps talking. Sparkie is our prototype of that teammate.

**On stage:** Open with the goal. The photo is an editorial illustration, not a Sparkie session.

## 02 — Keep the context. Start the work.

In a meeting, the useful context is spread across the conversation: the options we considered, the constraints, and what we decided. A separate chat makes someone explain it all again. We want to ask for a comparison, a file, or an edit right there in the discussion. The agent should participate when invited and work in the background while people continue. That is what we mean by a meeting agent with shared context.

**On stage:** Emphasize shared conversation and work during the meeting. This is the product goal, not unlimited memory: the current system only receives the session input available after it joins; tasks receive a snapshot at delegation.

## 03 — Where Sparkie fits.

Granola focuses on meeting memory. We want a speaking participant as well. Vapi provides voice agents connected to tools; the shared-meeting behavior still needs to be built. ZoomMate already connects meeting context to workflows, so executing work is not unique to us. Our focus is the bridge from a shared meeting to an agent in our own project: its files, commands, and tools. The team keeps talking and can review the result together.

**On stage:** Place this directly after motivation. Four comparisons: existing value, the specific bridge we built, then Sparkie. Do not claim competitors cannot execute work. Official sources are available in the source drawer.

## 04 — What we built.

Here is the actual frontend. The workspace brings the conversation, task center and artifacts together. The transcript makes the request inspectable. The task panel shows status and backend tool activity while the voice remains available. When the worker finishes, the result opens as an artifact that we can read and refine. These screenshots come from a completed local voice session. Next, we will show the supplied Zoom demo video.

**On stage:** Four views: workspace, transcript, tasks, artifact. Click a capture to enlarge it. The task screenshot shows completed work; it is not a live progress feed. These captures are separate from the Zoom recording.

## 05 — Watch it in the meeting.

Now watch the meeting experience. Follow the spoken request, the background work, and the result the team can inspect. The important connection is that the discussion and the work happen in the same session.

**On stage:** Play the supplied YouTube demo. The player uses the full recording; 60 seconds is a suggested talk allowance, not an automatic trim or a measured task duration. Let the actual clip establish what happened. The adjacent About Sparkie report comes from a separate local voice session.

## 06 — From conversation to action.

Zoom supplies separate human audio tracks. Deepgram gives us the words, and Realtime semantic turn detection estimates when the thought is complete. Gemini makes the participation decision. An accepted turn reaches the foreground Realtime voice agent, which can delegate work to a separate Devin or Codex worker. Results return through the task center. The difficult part is the decision in the middle: should the agent speak at all?

**On stage:** Four builds: input, routing, voice, worker. End on Gemini to introduce the dedicated next page. In this Zoom mode the foreground receives assembled text; separate Realtime sessions handle semantic audio completion.

## 07 — When should Sparkie speak?

The hard part is deciding when to participate. A name match is not enough: people can talk about Sparkie without talking to it. The reverse also happens: “Which one would you choose?” can clearly be a follow-up without a name. We use Gemini as a dedicated, tool-free router. It sees the completed current utterance, the speaker identity, and up to eight recent human and assistant entries. It returns accept or reject. Accept lets the foreground voice respond to this turn. Reject keeps it quiet while listening continues. We reassess each turn; an earlier response is not permanent permission to talk. If the recipient is unclear, or routing fails, it stays quiet.

**On stage:** This is the central technical page. Click Mention, Follow-up, and Ambiguous. Examples illustrate the implemented policy; they are not new live classifier measurements. Gemini decides participation, not speech endpoints or playback interruption. Confirmed human speech has a separate priority path that stops playback. The eight-entry router window is distinct from meeting context and task snapshots.

## 08 — Keep talking while work continues.

The voice loop and the task worker run separately. The worker starts with the transcript snapshot available when the task is delegated. People can keep discussing and interrupt the voice without automatically cancelling that task. The result returns for review when ready. If the discussion changes the requirements, an explicit update carries that change into the work.

**On stage:** Four beats: delegate, background work, voice interruption, result. The diagram explains control flow; its progress bar is not live telemetry or a latency measurement.

## 09 — What still needs work.

This is still a prototype. Setup is not one click: it needs the Zoom SDK, provider credentials, CLI login, and platform permissions. Our primary path is macOS Zoom with English speech. Wake decisions, turn boundaries and acoustic echo can still be wrong; latency varies across providers and tasks. Recovery after input failures is limited. And later decisions do not silently update a running task: we need an explicit follow-up.

**On stage:** Be concrete about what is missing. No latency numbers without measurements. The agent processes meeting audio; it does not inspect participants’ screens or video.

## 10 — Make it easier to invite.

Next, we want to package setup so inviting Sparkie is much easier, improve recovery and measure the participation decisions, and make task updates easier to follow. The goal stays the same: a teammate with the meeting context, ready to help while the conversation is still happening.

**On stage:** These are directions, not completed features or promised dates. Close on the product goal, then take questions.

## Implementation references

- Gemini routing policy and eight-entry context window: src/sparkie/wake_router.py.
- Quiet on errors, superseded-turn handling and explicit local controls: src/sparkie/realtime.py.
- Setup and current scope: README.md and docs/manual-setup.md.
- Screenshot provenance: assets/CREDITS.md.

“Active” and “Quiet” describe the participation decision for the current turn, not permanent modes or a promise of unsolicited intervention. Quiet does not discard meeting context. Foreground session context, the router window and a worker’s task snapshot are distinct.
