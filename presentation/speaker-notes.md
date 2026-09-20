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
| 3 | The gap is in the handoff. | 4 | 60s | 1:40 |
| 4 | Imagine the room. | 6 | 45s | 2:25 |
| 5 | Watch the work happen. | 1 | 60s | 3:25 |
| 6 | Two rhythms. One teammate. | 4 | 35s | 4:00 |
| 7 | Read the room. | 3 | 25s | 4:25 |
| 8 | Inside the loop. | 4 | 45s | 5:10 |
| 9 | From request to review. | 3 | 45s | 5:55 |
| 10 | Leave with work in hand. | 1 | 15s | 6:10 |

## Demo preparation

Insert a real 60-second Zoom excerpt and an actual artifact screenshot using media-config.js. Show discussion → explicit delegation → the saved file → follow-up edit. A human opens and shares the file. Label shortened waits. Until media is supplied, identify the slot as a planned demo; do not present the placeholder as evidence.

## 01 — Meet your fourth teammate. (20s)

Picture a teammate who joins the Zoom call and understands the discussion already in progress. Sparkie can answer aloud, take on a task in your project, and return with a result. Our question is simple: can the work start before everyone leaves the meeting?

**On stage:** Open on the photograph. It illustrates collaboration, not a real Sparkie session.

## 02 — Can someone take this forward? (20s)

The team has chosen a direction. Someone now has to reconstruct the discussion, compare the options, and make the actual file. That handoff is the moment we are trying to shorten: the intention is already shared, so why lose the context before the work begins?

**On stage:** Pause on the question; keep this short.

## 03 — The gap is in the handoff. (60s)

Granola is strong at meeting memory without a bot. That design does not give the notepad a speaking seat. Vapi connects voice to tools, but a builder still needs the meeting transport and shared-context application. ZoomMate is the closest comparison: it already combines context and execution, through Zoom’s product surfaces and connectors. Sparkie explores a different workbench: the project itself, reached through spoken delegation and refined in the room. The cost is real too: this is a macOS Zoom prototype with setup, broad tool access, and human review. These are design tradeoffs, not a claim that other products cannot act.

**On stage:** Four beats: Granola → Vapi → ZoomMate → Sparkie. Official product links and images are on the slide. Explain each strength before its tradeoff. Zoom comparison is a product-surface distinction, not an assertion that Zoom lacks agent execution.

## 04 — Imagine the room. (45s)

Here is a product review. One person favors guided onboarding, another a simpler checklist. Now the instruction to Sparkie has meaning: compare those options using the discussion as context. Change the room to a customer call. The customer moves reporting ahead of the dashboard. The follow-up should reflect that shift, without inventing a deadline. These are illustrative conversations. The point is that a useful request grows out of the shared discussion, rather than starting as a blank chat prompt.

**On stage:** Six beats: three dialogue turns in each of two scenes. Read only the key line from each beat. Names identify roles, not real people. Use the next slide for real-session evidence.

## 05 — Watch the work happen. (60s)

In the real demo, the team is planning the film you are watching. Sparkie receives the request to create the outline while the discussion continues. We open the real file, then ask it to incorporate the agreed recording roles. Listen for the acknowledgement, but look at the file for evidence of completion.

**On stage:** Use a real 60-second clip. Placeholder imagery is not evidence. Label shortened waits. A human opens and shares the file. If no recording is supplied, describe the planned demo slot honestly.

## 06 — Two rhythms. One teammate. (35s)

An acknowledgement belongs to the voice loop. Execution belongs to a separate worker. The worker starts with the finalized transcript available at delegation and works in the project while the room continues talking. If a person interrupts, the voice yields; this does not automatically cancel the task. A completed result returns through the task layer and can be reported at a quiet moment.

**On stage:** Four beats: delegate, work while talking, human interruption, result. The illuminated routes are a conceptual sequence, not measured timing. Task cancellation is an explicit operation.

## 07 — Read the room. (25s)

The same assistant needs judgment about participation. Mentioning Sparkie in discussion is not always an invitation. A pause inside a request should not throw away the rest of the thought. And when a person corrects the request, the voice should yield. We handle these as different signals in the same conversation, rather than one mute switch.

**On stage:** Three beats: indirect mention, complete request with a pause, explicit correction. This is a scripted illustration, not a model benchmark. If asked: medium semantic VAD; a 350ms unconfirmed interruption candidate can resume buffered audio. Confirmed speech cancels the reply.

## 08 — Inside the loop. (45s)

Separate human tracks enter from Zoom. Two parallel adapters supply the words and semantic turn completion. After those agree on a complete turn, Gemini checks whether it addresses Sparkie. Realtime handles the voice. Fast speech confirmation also has a priority path to stop playback. When a task is delegated, a transcript snapshot reaches the Devin worker with project tools. Its result returns through the task center to the voice. The bot’s own SDK track is excluded, although physical speaker echo can still reenter a human microphone.

**On stage:** Four builds: input split, complete-turn routing, voice and interruption path, asynchronous worker return. Current worker is SWE 1.6 Fast; Codex is selectable. The foreground consumes assembled text in this mode; separate Realtime sessions perform semantic audio completion.

## 09 — From request to review. (45s)

Here is what a useful handoff looks like at the artifact level. The documented Zoom demo creates an outline, then updates it with roles; the file must be opened and checked. For a concrete engineering walkthrough, an unused audio queue provides a failure to reproduce, a boundary to fix, and a regression to verify. For a customer follow-up, the useful output preserves priorities and explicitly leaves an unagreed date open. The latter two are worked scenarios. We are showing what to ask for and how to judge the result, not claiming every workflow has been run successfully in a meeting.

**On stage:** Three beats: demo film, bug triage, customer follow-up. Artifact panels are labelled illustrative or expected. Real-session evidence belongs in the recording slot. Keep the acceptance check visible.

## 10 — Leave with work in hand. (15s)

Sparkie brings the conversation and the work into the same room. Address it, delegate a concrete task, and refine the result together. That is the experience we want to build: useful progress before the call ends.

**On stage:** End here. The visible links lead to the project homepage and repository, not backwards to another slide.

## Timing variants

For a shorter talk, keep all build steps but summarize the product comparison in 40 seconds, inspiration in 30, the system diagram in 30 and the playbooks in 30. This reduces the base to 5:05. For a seven-minute talk, add 20 seconds to the real demo and 25 seconds to discuss one practical case, reaching 6:55.

## Questions to be ready for

**Is this unique?** No claim of exclusivity. Zoom and other products already execute work. Our specific focus is spoken collaboration with an agent directly in the project, from within a shared meeting.

**How does it know a request is complete?** Deepgram words and separate per-participant Realtime semantic completion are aligned before Gemini wake routing. Current semantic VAD eagerness is medium.

**What happens to the background job when I interrupt?** Voice interruption does not itself cancel the delegated task. Task cancellation is explicit. Unconfirmed noise candidates can resume buffered audio after the 350ms candidate window; confirmed speech cancels the current reply.

**Does it automatically absorb later decisions?** The worker starts with the finalized transcript snapshot at delegation. Give an explicit update or follow-up to incorporate later decisions.

**Does excluding the bot track solve echo?** It avoids feeding the bot’s own SDK track back in. Physical loudspeaker audio can still enter a human microphone.

**Which examples were actually run?** The README documents the Zoom demo outline and follow-up workflow. The engineering and customer cases are worked scenarios, and their on-screen artifacts are illustrative or expected. Real media must show actual output.

**Which models are configured?** GPT Realtime 2.1; Deepgram Nova-3; Gemini 3.5 Flash Minimal through tool-free Devin ACP; Devin SWE 1.6 Fast, with Codex selectable.

See research.md for the full comparison, evidence and boundaries; assets/CREDITS.md for image sources.
