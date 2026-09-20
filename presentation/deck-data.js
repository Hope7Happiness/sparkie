/* Presentation content is local: no API, analytics, or network dependency. */
window.SPARKIE_DECK = {
  slides: [
    {title: 'Meet your fourth teammate.', chapter: 'AN EXTRA SEAT AT THE TABLE', seconds: 20,
      notes: 'Imagine a teammate who joins your Zoom call, understands what the team is discussing, and can actually take on a piece of the work. That is Sparkie. You speak to it in the meeting. It responds by voice, works in the project, and comes back with a result.',
      cue: 'Start with the room, not the model names. Make eye contact. The opening art is an illustration, not a live meeting.'},
    {title: 'Can someone take this forward?', chapter: 'A FAMILIAR MOMENT', seconds: 25,
      notes: 'We have all had this moment. The conversation was useful. We chose a direction. Then someone has to reconstruct the context, do the research, and make the actual file. The handoff takes us out of the shared conversation. We are exploring what happens when the work can begin while everyone is still in the room.',
      cue: 'Give the question a short pause. Do not attach an invented time-saving statistic to the handoff.'},
    {title: 'AI already has a seat at work.', chapter: 'THE LANDSCAPE', seconds: 35,
      notes: 'There is already a rich landscape here. Granola, Otter, and Fireflies turn meetings into useful knowledge and follow-up workflows. Vapi, Retell, and ElevenLabs connect voice conversations to business processes. Zoom also offers agentic work execution. These categories overlap. Our focus is a particular experience: a participant in a shared meeting who can work directly in your project, and take another instruction as the discussion evolves.',
      cue: 'Click Converse and Execute once. These are product focuses, not a claim that competitors cannot act. The source drawer contains official product references.'},
    {title: 'Say it. Stay in the room.', chapter: "SPARKIE'S FOCUS", seconds: 35,
      notes: 'Think of Sparkie as a workbench you can reach by speaking. Ask it to compare the approaches the team just discussed. Ask it to make the first draft. Then ask it to revise that draft using a new decision. The important part is shared context: you are not opening a separate chat and explaining the whole meeting again. Each new instruction is explicit, and the output is something the team can inspect.',
      cue: 'Click Explore, Create, then Refine. These requests are illustrative. Introduce the next slide as the real evidence.'},
    {title: 'Watch the work happen.', chapter: 'THE END-TO-END MOMENT', seconds: 75,
      notes: 'Here is the real loop. Our team is meeting to plan a demo video. Sparkie has heard the discussion. We ask it to write an outline, and continue talking about who will record and edit. Then we open the generated file. Finally, we ask Sparkie to add the roles we have just agreed on. The output changes as the conversation moves forward.',
      cue: 'Use a 60–75 second excerpt from the real Zoom session. Show: discussion → explicit request → actual file → follow-up edit. Stop narrating while Sparkie speaks. If a wait is shortened, label that edit. Until real media is inserted, say clearly that this is the planned demo slot; the placeholder is not evidence. Do not claim automatic screen sharing: a human opens and shares the file.'},
    {title: 'Two rhythms. One teammate.', chapter: 'KEEP THE MEETING MOVING', seconds: 30,
      notes: 'Two things are happening at once. The foreground handles the conversation. A separate background worker does the task with the transcript context available when it was delegated. That is why a longer piece of work does not have to freeze the meeting. When the result is ready, Sparkie can report it in a quiet moment. If the team makes a later decision, an explicit update or follow-up carries it into the work.',
      cue: 'Trace the upper lane, then the lower lane, then the return. The animation is a conceptual sequence, not a latency measurement.'},
    {title: 'A pause is part of the conversation.', chapter: 'THE CONVERSATION LAYER', seconds: 40,
      notes: 'The hard part is not just producing a voice. It is deciding when to use it. We separate three questions. Has someone started speaking? Have they finished their thought? And were they speaking to Sparkie? Deepgram gives us words and quick speech activity. Realtime semantic VAD estimates when the turn is complete. Gemini checks whether the full request addresses Sparkie. This lets a natural pause stay inside a request, while real human speech can interrupt the reply.',
      cue: 'Click Wait for the thought, Know when to join, and Give the floor back. If asked: semantic VAD is set to medium. A noise candidate pauses playback for up to 350ms; without text confirmation it resumes buffered audio. Confirmed speech cancels the current reply. These are probabilistic behaviors, not perfect acoustic echo cancellation.'},
    {title: 'A voice up front. An agent at work.', chapter: 'UNDER THE HOOD', seconds: 45,
      notes: 'For the technical view, start on the left. The Zoom Meeting SDK gives us separate participant audio tracks. We exclude the bot’s own SDK track. Deepgram transcripts and Realtime semantic endpoints are aligned before the full turn reaches the Gemini wake router. GPT Realtime then handles the voice conversation. It can delegate to a separate Devin worker, currently SWE 1.6 Fast, with file, shell, network, and configured tool access. Results return through the task layer to the voice. The shared contracts let us change providers without rebuilding the meeting transport.',
      cue: 'Use the large verbs for nontechnical listeners; use provider names only once. Clarify if asked: the foreground receives assembled text in this mode, while separate per-participant Realtime sessions hear audio for semantic completion. Codex is an alternate worker. Acknowledgement is not proof of a completed action.'},
    {title: 'Where would you invite Sparkie?', chapter: 'IMAGINE YOUR NEXT MEETING', seconds: 40,
      notes: 'Now change the room. In an engineering discussion, imagine asking it to inspect the repository and prepare a patch for review. In a research discussion, ask it to compare the evidence behind two claims. In a customer call, turn the priorities you just heard into a tailored follow-up draft. The same pattern extends to a product brief, an interview debrief, or a launch checklist. These are scenarios to explore with the tool-backed agent, not claims that every integration or workflow has already been validated.',
      cue: 'Pick two or three rooms that fit this audience. Let someone choose a room if time allows. Each result is introduced with Imagine. These scenarios illustrate possibilities, not additional tested integrations. External systems require the relevant tools and access; do not promise autonomous sending, hiring decisions, deployments, or screen understanding.'},
    {title: 'Leave with work in hand.', chapter: 'THE INVITATION', seconds: 20,
      notes: 'Sparkie is a working prototype of a teammate inside the meeting: it listens, responds when addressed, takes on work, and returns a result the team can refine. We want a good conversation to become useful progress before the call ends. Which meeting would you invite it to?',
      cue: 'Finish on the question. Invite discussion or return to the scenario slide. The tested demo path is macOS Zoom with English speech; do not imply every platform or long-session reliability is proven.'}
  ],
  market: [
    'Meeting knowledge → follow-through.',
    'A conversation → a workflow.',
    'Workplace context → completed work.'
  ],
  requests: [
    ['“Sparkie, compare the two approaches.”', 'A comparison with sources'],
    ['“Sparkie, write the outline.”', 'A file the team can open'],
    ['“Sparkie, add the roles we agreed on.”', 'The same artifact, updated']
  ],
  speech: {
    pause: ['“Sparkie, could you … check the README?”', 'Wait for the thought. Then decide whether to reply.'],
    address: ['“Sparkie is our meeting assistant.”', 'A name in the discussion is not automatically an invitation.'],
    interrupt: ['“Sparkie, wait — just the short version.”', 'Confirmed human speech stops the current reply.']
  },
  rooms: [
    {context: 'THE TEAM JUST CHOSE A DIRECTION.', prompt: '“Sparkie, turn that decision into a product brief.”', output: 'Imagine: a brief to refine.', art: 'BRIEF'},
    {context: 'THE TEAM IS TRIAGING A BUG.', prompt: '“Sparkie, inspect the repo for that failure and draft a fix.”', output: 'Imagine: a patch to review.', art: 'PATCH'},
    {context: 'TWO CLAIMS. ONE OPEN QUESTION.', prompt: '“Sparkie, compare the evidence for both sides.”', output: 'Imagine: a sourced comparison.', art: 'SOURCES'},
    {context: 'THE CUSTOMER JUST SHARED THEIR PRIORITIES.', prompt: '“Sparkie, draft a follow-up around their priorities.”', output: 'Imagine: a tailored draft.', art: 'FOLLOW-UP'},
    {context: 'INTERVIEWERS ARE COMPARING OBSERVATIONS.', prompt: '“Sparkie, organize our notes against the rubric.”', output: 'Imagine: a structured debrief.', art: 'DEBRIEF'},
    {context: 'THE LAUNCH PLAN JUST CHANGED.', prompt: '“Sparkie, update the project checklist with those changes.”', output: 'Imagine: an updated checklist.', art: 'CHECKLIST'}
  ],
  sources: [
    {name: 'Granola', url: 'https://www.granola.ai/', summary: 'Meeting notes, cross-meeting context, preparation, and post-meeting drafts. Its published capture approach does not invite a meeting bot.'},
    {name: 'Otter', url: 'https://otter.ai/', summary: 'Meeting knowledge, summaries, action items, CRM connections, and additional sales/recruiting agent use cases. Not limited to transcription.'},
    {name: 'Fireflies', url: 'https://fireflies.ai/', summary: 'Meeting capture and analysis, follow-up drafts, CRM updates, project-task creation, and MCP access to meeting knowledge.'},
    {name: 'Vapi', url: 'https://vapi.ai/', summary: 'A voice-agent platform for builders. Published use cases include customer support, lead qualification, and appointment scheduling.'},
    {name: 'Retell', url: 'https://www.retellai.com/', summary: 'Phone agents and contact-center workflows, including appointment booking, qualification, system updates, and human handoffs.'},
    {name: 'ElevenLabs Agents', url: 'https://elevenlabs.io/agents', summary: 'Conversational agents with tools and workflows for support, sales, operations, and more across voice and other channels.'},
    {name: 'Zoom / ZoomMate', url: 'https://www.zoom.com/en/products/ai-assistant/', summary: 'The official AI-assistant page currently presents ZoomMate: meeting/workplace context, research, document creation, task delegation, and connected workflows.'}
  ]
};
