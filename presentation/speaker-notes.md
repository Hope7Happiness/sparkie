# Sparkie — English speaker outline

Target: **6:10**. Ten slides, **28 presentation items**, including a 60-second real-demo window. English delivery for a mixed technical and nontechnical audience.

## Delivery controls

Press Right or Space to reveal the next item; only after the final item does it advance to the next slide. Left reverses that sequence. Page Down / Page Up skip whole slides. The on-screen arrows, touch swipes and speaker-view arrows follow the same item sequence. P opens a separate speaker view synchronized to the current slide and item.

Do not read all visible dialogue verbatim. Give the scene its premise, let the next line appear, then land the request. The photos are editorial scene illustrations; product captures are official websites. Illustrative dialogue and artifact structures are not real-session evidence.

## Run of show

| Slide | Moment | Items | Time | Cumulative |
| --- | --- | --- | --- | --- |
| 1 | Meet your fourth teammate. | 1 | 20s | 0:20 |
| 2 | Can someone take this forward? | 1 | 20s | 0:40 |
| 3 | We close the handoff gap. | 4 | 60s | 1:40 |
| 4 | Imagine the room. | 6 | 45s | 2:25 |
| 5 | Watch the work happen. | 1 | 60s | 3:25 |
| 6 | Two rhythms. One teammate. | 4 | 35s | 4:00 |
| 7 | Read the room. | 3 | 25s | 4:25 |
| 8 | Inside the loop. | 4 | 45s | 5:10 |
| 9 | From request to review. | 3 | 45s | 5:55 |
| 10 | Leave with work in hand. | 1 | 15s | 6:10 |

## Demo preparation

Insert a real 60-second Zoom excerpt and an actual artifact screenshot using media-config.js. The longer session follows the [continuous three-person rehearsal script](../frontend/public/demo-script.html): discussion → delegation → real Tasks activity while people agree roles → present the outline → review roles → update the same document → present the latest artifact.

- Rehearse the same Zoom session and workspace. Keep the actual Tasks panel visible during role discussion. Status and tool-action text are event-driven; do not add a fictional percentage, ETA, or streaming document preview.
- Ask the worker to save demo-outline.md **and return the complete Markdown body**. Ask for the full body again after the role update. The live artifact contains the task result; a file path or “saved” message does not display the document.
- After a ready result, say “Sparkie, show us the outline.” After the follow-up completes, say “Sparkie, show us the updated outline.” Verify that the selected artifact is the intended result; presentation selects the latest ready artifact. If the embedded board already shows it, skip the redundant request. If voice presentation fails, use Present on the correct card and describe the fallback accurately.
- Browser artifact presentation and sharing that browser window into Zoom are distinct steps. Rehearse the actual sharing path and confirm that another participant sees the intended content. Do not infer remote visibility from the local panel.
- Select the key moments for the 60-second excerpt; this is a playback budget, not an end-to-end performance claim. Label shortened waits and retain the actual agent voice. Until media is supplied, identify the slot as planned and keep the placeholder label.
- The light “we’ve been recording” ending in the rehearsal script only applies when recording has actually been running. Otherwise use the ordinary “Great. Let’s record it.” ending.

## 01 — Meet your fourth teammate. (20s)

Picture a teammate who joins the Zoom call and understands the discussion already in progress. Sparkie can answer aloud, take on a task in your project, and return with a result. Our question is simple: can the work start before everyone leaves the meeting?

**On stage:** Open on the photograph. It illustrates collaboration, not a real Sparkie session.

## 02 — Can someone take this forward? (20s)

The team has chosen a direction. Someone now has to reconstruct the discussion, compare the options, and make the actual file. That handoff is the moment we are trying to shorten: the intention is already shared, so why lose the context before the work begins?

**On stage:** Pause on the question; keep this short.

## 03 — We close the handoff gap. (60s)

Granola gives us meeting memory. What is missing from that notepad experience is a speaking teammate who can take the task right there in the call. Sparkie adds that participant. Vapi gives developers voice agents and tools. But the shared-meeting workflow still has to be built: who is speaking, when the agent should join in, and how the work reaches the project. Sparkie connects that loop. ZoomMate already turns meeting context into connected workflows. For our team, the last mile is our own CLI workspace: the repository, commands and files. Sparkie connects the meeting directly to that workbench. We close the handoff gap: the team keeps discussing, the agent does the work, and everyone can refine the result in the same room.

**On stage:** Four beats, about 15 seconds each. For each competitor: what they deliver → the specific gap in this experience → what Sparkie adds. Land on the Sparkie result, not a list of caveats. The Zoom gap is the extra bridge to a project-local CLI workflow; do not broaden it into a claim that Zoom cannot execute tasks or integrate developer tools. Supporting scope and prototype limitations remain in research.md and Q&A.

## 04 — Imagine the room. (45s)

Here is a product review. One person favors guided onboarding, another a simpler checklist. Now the instruction to Sparkie has meaning: compare those options using the discussion as context. Change the room to a customer call. The customer moves reporting ahead of the dashboard. The follow-up should reflect that shift, without inventing a deadline. These are illustrative conversations. The point is that a useful request grows out of the shared discussion, rather than starting as a blank chat prompt.

**On stage:** Six beats: three dialogue turns in each of two scenes. Read only the key line from each beat. Names identify roles, not real people. Use the next slide for real-session evidence.

## 05 — Watch the work happen. (60s)

The team is planning the film you are watching. Sparkie takes the outline task; while it works, the team agrees who will narrate, record, and edit. Watch the real task status and tool activity beside the conversation. When the outline is ready, they ask Sparkie to show it, review the roles against it, and request a follow-up update. The final artifact brings the outline and agreed roles together. Listen for the acknowledgement, but inspect the actual content for completion.

**On stage:** Use a real 60-second excerpt: delegation → Tasks activity during role discussion → show us the outline → confirmed roles → update activity → latest artifact. These are selected moments from a longer session, not a 60-second latency claim. Label shortened waits. Verify the right workspace and artifact version. If voice presentation fails, click Present; describe a manual fallback honestly. Keep placeholders labelled until real media is supplied.

## 06 — Two rhythms. One teammate. (35s)

An acknowledgement belongs to the voice loop. Execution belongs to a separate worker. It starts with the finalized transcript available at delegation while the team keeps talking. Actual task events can show whether it is queued, running, or done, and which tool action is underway. Human interruption yields the voice without automatically cancelling the task. The completed result can be reported aloud and inspected as an artifact. Later decisions need an explicit follow-up.

**On stage:** Four beats: delegate, work while talking, human interruption, result. Slide routes and the illustrated progress bar are conceptual, not live telemetry or measured timing. Real Tasks activity is shown in the recording: status and tool actions, without a completion percentage or time estimate. Task cancellation is explicit.

## 07 — Read the room. (25s)

The same assistant needs judgment about participation. Mentioning Sparkie in discussion is not always an invitation. A pause inside a request should not throw away the rest of the thought. And when a person corrects the request, the voice should yield. We handle these as different signals in the same conversation, rather than one mute switch.

**On stage:** Three beats: indirect mention, complete request with a pause, explicit correction. This is a scripted illustration, not a model benchmark. If asked: medium semantic VAD; a 350ms unconfirmed interruption candidate can resume buffered audio. Confirmed speech cancels the reply.

## 08 — Inside the loop. (45s)

Separate human tracks enter from Zoom. Two parallel adapters supply the words and semantic turn completion. After those agree on a complete turn, Gemini checks whether it addresses Sparkie. Realtime handles the voice. Fast speech confirmation also has a priority path to stop playback. When a task is delegated, a transcript snapshot reaches the Devin worker with project tools. Its result returns through the task center to the voice. The bot’s own SDK track is excluded, although physical speaker echo can still reenter a human microphone.

**On stage:** Four builds: input split, complete-turn routing, voice and interruption path, asynchronous worker return. Current worker is SWE 1.6 Fast; Codex is selectable. The foreground consumes assembled text in this mode; separate Realtime sessions perform semantic audio completion.

## 09 — From request to review. (45s)

Here is what a useful handoff looks like at the artifact level. The demo plan asks for an outline, keeps real task activity visible while roles are discussed, then shows the result and adds the confirmed roles to the same document. Review the latest artifact against the saved file; a Done badge alone is not enough. For engineering, trace an audio queue failure, fix the boundary, and verify a regression. For a customer follow-up, preserve the priorities and leave unagreed dates open. The latter two are worked scenarios; the demo recording must supply the real-session evidence.

**On stage:** Three beats: demo film, bug triage, customer follow-up. Keep the illustrative or expected labels on these panels. The latest follow-up result can be a new artifact even though it updates the same file. Only the supplied real recording demonstrates which presentation and execution steps actually succeeded.

## 10 — Leave with work in hand. (15s)

Sparkie brings the conversation and the work into the same room. Address it, delegate a concrete task, and refine the result together. That is the experience we want to build: useful progress before the call ends.

**On stage:** End here. The visible links lead to the project homepage and repository, not backwards to another slide.

## Timing variants

For a shorter talk, keep all build steps but summarize the product comparison in 40 seconds, inspiration in 30, the system diagram in 30 and the playbooks in 30. This reduces the base to 5:05. For a seven-minute talk, add 20 seconds to the real demo and 25 seconds to discuss one practical case, reaching 6:55.

## Questions to be ready for

**Is the progress display real?** The Tasks panel uses actual status and backend tool events. It does not expose a completion percentage, an ETA, or a live document draft. The animated routes and progress illustration on slide 6 explain the architecture; they are not a recording of those events.

**What does the artifact show?** The full returned task result, not a live view of an arbitrary project file. Ask for the complete body after creation and after edits, then verify the latest artifact against the saved file.

**Does “show us” prove everyone in Zoom can see it?** No. It requests artifact presentation; remote visibility depends on the sharing path used in that session. Confirm it from another participant during rehearsal.

**Is this unique?** No claim of exclusivity. Zoom and other products already execute work. Our specific focus is spoken collaboration with an agent directly in the project, from within a shared meeting.

**How does it know a request is complete?** Deepgram words and separate per-participant Realtime semantic completion are aligned before Gemini wake routing. Current semantic VAD eagerness is medium.

**What happens to the background job when I interrupt?** Voice interruption does not itself cancel the delegated task. Task cancellation is explicit. Unconfirmed noise candidates can resume buffered audio after the 350ms candidate window; confirmed speech cancels the current reply.

**Does it automatically absorb later decisions?** The worker starts with the finalized transcript snapshot at delegation. Give an explicit update or follow-up to incorporate later decisions.

**Does excluding the bot track solve echo?** It avoids feeding the bot’s own SDK track back in. Physical loudspeaker audio can still enter a human microphone.

**Which examples were actually run?** The README documents the Zoom demo outline and follow-up workflow. The engineering and customer cases are worked scenarios, and their on-screen artifacts are illustrative or expected. Real media must show actual output.

**Which models are configured?** GPT Realtime 2.1; Deepgram Nova-3; Gemini 3.5 Flash Minimal through tool-free Devin ACP; Devin SWE 1.6 Fast, with Codex selectable.

See research.md for the full comparison, evidence and boundaries; assets/CREDITS.md for image sources.
