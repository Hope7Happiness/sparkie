# Sparkie — English speaker outline

Target: **6:05**, including a 75-second real-demo window. Ten slides. Designed for a mixed technical and nontechnical audience.

## Run of show

| Slide | Moment | Time | Cumulative |
| --- | --- | --- | --- |
| 1 | Meet your fourth teammate. | 20s | 0:20 |
| 2 | Can someone take this forward? | 25s | 0:45 |
| 3 | AI already has a seat at work. | 35s | 1:20 |
| 4 | Say it. Stay in the room. | 35s | 1:55 |
| 5 | Watch the work happen. | 75s | 3:10 |
| 6 | Two rhythms. One teammate. | 30s | 3:40 |
| 7 | A pause is part of the conversation. | 40s | 4:20 |
| 8 | A voice up front. An agent at work. | 45s | 5:05 |
| 9 | Where would you invite Sparkie? | 40s | 5:45 |
| 10 | Leave with work in hand. | 20s | 6:05 |

## Before you take the floor

Open index.html and press P for a separate speaker window. Put the audience window on the shared display. Press F for fullscreen. T starts or pauses a local rehearsal timer; slides never advance automatically. The speaker timer is independent of the audience timer.

The visuals explain one simple idea: a teammate in the meeting can take a piece of the work into the project. The small technical explanations belong in this outline, not on the projected slide. Let the transitions finish; they carry the circles and artifact between scenes.

Choose two or three of the six scenarios that matter to this audience. Ask someone to pick a room if there is time. Interaction is illustrative, not a live inference call.

**Demo preparation:** insert a real Zoom recording and an actual artifact screenshot using media-config.js. The recording should show discussion → explicit request → actual file → follow-up edit. Cut to 60–75 seconds; label shortened waits. A human opens/shares the file. If media is still missing, introduce slide 5 as a planned demo and walk through the sequence without claiming that a placeholder proves it.

## 01 — Meet your fourth teammate. (20s)

Imagine a teammate who joins your Zoom call, understands what the team is discussing, and can actually take on a piece of the work. That is Sparkie. You speak to it in the meeting. It responds by voice, works in the project, and comes back with a result.

**On stage:** Start with the room, not the model names. Make eye contact. The opening art is an illustration, not a live meeting.

## 02 — Can someone take this forward? (25s)

We have all had this moment. The conversation was useful. We chose a direction. Then someone has to reconstruct the context, do the research, and make the actual file. The handoff takes us out of the shared conversation. We are exploring what happens when the work can begin while everyone is still in the room.

**On stage:** Give the question a short pause. Do not attach an invented time-saving statistic to the handoff.

## 03 — AI already has a seat at work. (35s)

There is already a rich landscape here. Granola, Otter, and Fireflies turn meetings into useful knowledge and follow-up workflows. Vapi, Retell, and ElevenLabs connect voice conversations to business processes. Zoom also offers agentic work execution. These categories overlap. Our focus is a particular experience: a participant in a shared meeting who can work directly in your project, and take another instruction as the discussion evolves.

**On stage:** Click Converse and Execute once. These are product focuses, not a claim that competitors cannot act. The source drawer contains official product references.

## 04 — Say it. Stay in the room. (35s)

Think of Sparkie as a workbench you can reach by speaking. Ask it to compare the approaches the team just discussed. Ask it to make the first draft. Then ask it to revise that draft using a new decision. The important part is shared context: you are not opening a separate chat and explaining the whole meeting again. Each new instruction is explicit, and the output is something the team can inspect.

**On stage:** Click Explore, Create, then Refine. These requests are illustrative. Introduce the next slide as the real evidence.

## 05 — Watch the work happen. (75s)

Here is the real loop. Our team is meeting to plan a demo video. Sparkie has heard the discussion. We ask it to write an outline, and continue talking about who will record and edit. Then we open the generated file. Finally, we ask Sparkie to add the roles we have just agreed on. The output changes as the conversation moves forward.

**On stage:** Use a 60–75 second excerpt from the real Zoom session. Show: discussion → explicit request → actual file → follow-up edit. Stop narrating while Sparkie speaks. If a wait is shortened, label that edit. Until real media is inserted, say clearly that this is the planned demo slot; the placeholder is not evidence. Do not claim automatic screen sharing: a human opens and shares the file.

## 06 — Two rhythms. One teammate. (30s)

Two things are happening at once. The foreground handles the conversation. A separate background worker does the task with the transcript context available when it was delegated. That is why a longer piece of work does not have to freeze the meeting. When the result is ready, Sparkie can report it in a quiet moment. If the team makes a later decision, an explicit update or follow-up carries it into the work.

**On stage:** Trace the upper lane, then the lower lane, then the return. The animation is a conceptual sequence, not a latency measurement.

## 07 — A pause is part of the conversation. (40s)

The hard part is not just producing a voice. It is deciding when to use it. We separate three questions. Has someone started speaking? Have they finished their thought? And were they speaking to Sparkie? Deepgram gives us words and quick speech activity. Realtime semantic VAD estimates when the turn is complete. Gemini checks whether the full request addresses Sparkie. This lets a natural pause stay inside a request, while real human speech can interrupt the reply.

**On stage:** Click Wait for the thought, Know when to join, and Give the floor back. If asked: semantic VAD is set to medium. A noise candidate pauses playback for up to 350ms; without text confirmation it resumes buffered audio. Confirmed speech cancels the current reply. These are probabilistic behaviors, not perfect acoustic echo cancellation.

## 08 — A voice up front. An agent at work. (45s)

For the technical view, start on the left. The Zoom Meeting SDK gives us separate participant audio tracks. We exclude the bot’s own SDK track. Deepgram transcripts and Realtime semantic endpoints are aligned before the full turn reaches the Gemini wake router. GPT Realtime then handles the voice conversation. It can delegate to a separate Devin worker, currently SWE 1.6 Fast, with file, shell, network, and configured tool access. Results return through the task layer to the voice. The shared contracts let us change providers without rebuilding the meeting transport.

**On stage:** Use the large verbs for nontechnical listeners; use provider names only once. Clarify if asked: the foreground receives assembled text in this mode, while separate per-participant Realtime sessions hear audio for semantic completion. Codex is an alternate worker. Acknowledgement is not proof of a completed action.

## 09 — Where would you invite Sparkie? (40s)

Now change the room. In an engineering discussion, imagine asking it to inspect the repository and prepare a patch for review. In a research discussion, ask it to compare the evidence behind two claims. In a customer call, turn the priorities you just heard into a tailored follow-up draft. The same pattern extends to a product brief, an interview debrief, or a launch checklist. These are scenarios to explore with the tool-backed agent, not claims that every integration or workflow has already been validated.

**On stage:** Pick two or three rooms that fit this audience. Let someone choose a room if time allows. Each result is introduced with Imagine. These scenarios illustrate possibilities, not additional tested integrations. External systems require the relevant tools and access; do not promise autonomous sending, hiring decisions, deployments, or screen understanding.

## 10 — Leave with work in hand. (20s)

Sparkie is a working prototype of a teammate inside the meeting: it listens, responds when addressed, takes on work, and returns a result the team can refine. We want a good conversation to become useful progress before the call ends. Which meeting would you invite it to?

**On stage:** Finish on the question. Invite discussion or return to the scenario slide. The tested demo path is macOS Zoom with English speech; do not imply every platform or long-session reliability is proven.

## Adjusting the length

- **About 5 minutes:** make the landscape 25 seconds, the focus 25, the demo 60, the two rhythms 20, the conversation layer 30, the architecture 35, and the scenarios 30. Keep the opening, handoff and close. Total: 4:50, leaving a little room for transitions.
- **About 7 minutes:** keep the base pacing and add 25 seconds for an audience-selected scenario plus 25 seconds to discuss a second demo artifact. Total: 6:55.

## If someone asks

**How is this different from meeting notes?** Meeting and workplace products already offer follow-ups and actions. Our focus is a particular interaction: a participant in a shared meeting, directly connected to project work, taking explicit follow-up instructions as the team discusses the result.

**Does it hear its own voice?** Its own SDK track is excluded. Speaker playback can still enter someone else’s microphone. This is not perfect acoustic echo cancellation.

**How does it know I finished?** Deepgram supplies words and speech activity; separate Realtime semantic detectors estimate complete turns, currently at medium eagerness. Full turns are aligned before Gemini wake routing.

**Does a task automatically learn later decisions?** It starts with the finalized transcript snapshot at delegation. Give an explicit update or follow-up for a later decision.

**Can it send, deploy, or change external systems?** The worker can use delegated tools with configured access. This presentation demonstrates project work, and does not claim that sending, deployments, or native integrations have been validated.

**What is proven?** The documented macOS Zoom loop includes real audio, transcripts, voice replies and delegated project work. The demo slot must show the actual recorded result. The six other rooms are scenarios to explore.

**Which models?** Current configuration: GPT Realtime 2.1 for voice and semantic turn detection, Deepgram Nova-3 for transcripts, Gemini 3.5 Flash Minimal via tool-free Devin ACP for wake routing, and Devin SWE 1.6 Fast for background work. Codex is selectable. Names and configuration can change; the architecture separates providers.

See research.md for official competitor sources and repository evidence.
