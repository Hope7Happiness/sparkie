/* Talk narrative. Captures are real local-session data; routing examples and diagrams are illustrative. */
window.SPARKIE_STORY = {
  "counts": [
    1,
    1,
    4,
    4,
    1,
    4,
    3,
    4,
    1,
    1
  ],
  "market": [
    {
      "name": "Granola",
      "url": "https://www.granola.ai/",
      "icon": "assets/market/granola-icon.ico",
      "image": "assets/market/granola-website.jpg",
      "fallback": "assets/market/granola-product.png",
      "strength": "Meeting memory without a bot.",
      "tradeoff": "A speaking participant is a different experience.",
      "focus": "Sparkie joins, answers, and takes on the work.",
      "label": "Meeting intelligence"
    },
    {
      "name": "Vapi",
      "url": "https://vapi.ai/",
      "icon": "assets/market/vapi-icon.ico",
      "image": "assets/market/vapi-website.jpg",
      "fallback": "assets/market/vapi-product.png",
      "strength": "Voice agents connected to tools.",
      "tradeoff": "The shared-meeting workflow is still yours to build.",
      "focus": "Sparkie connects Zoom, team context, and execution.",
      "label": "Voice infrastructure"
    },
    {
      "name": "ZoomMate",
      "url": "https://www.zoom.com/en/products/ai-assistant/",
      "icon": "assets/market/zoom-icon.ico",
      "image": "assets/market/zoom-website.jpg",
      "fallback": "assets/market/zoom-product.jpg",
      "strength": "Meeting context → connected workflows.",
      "tradeoff": "A project-local CLI requires another bridge.",
      "focus": "Sparkie puts the agent directly in your project.",
      "label": "Workplace execution"
    },
    {
      "name": "Sparkie",
      "url": "https://github.com/Hope7Happiness/sparkie",
      "icon": "assets/sparkie-mark.svg",
      "image": "assets/product/workspace.webp",
      "fallback": "assets/product/workspace.webp",
      "strength": "Shared context. Spoken delegation. Project execution.",
      "tradeoff": "Keep discussing. Inspect the file. Ask for the next edit.",
      "focus": "The conversation becomes work—in the same room.",
      "solvesLabel": "We connect",
      "gapLabel": "Your team can",
      "focusLabel": "The result",
      "label": "Local voice workspace"
    }
  ],
  "rhythm": [
    {
      "title": "Delegate a piece of the work.",
      "detail": "“Sparkie, write an outline from that discussion.”",
      "voice": "Acknowledge",
      "worker": "Context snapshot"
    },
    {
      "title": "The conversation keeps moving.",
      "detail": "The team agrees recording roles while real task events report activity.",
      "voice": "Available",
      "worker": "Tools + project files"
    },
    {
      "title": "Human speech gets the floor.",
      "detail": "A confirmed interruption stops the voice; the task can keep running.",
      "voice": "Yield to the room",
      "worker": "Still working"
    },
    {
      "title": "Return with something to inspect.",
      "detail": "The result can be reported aloud and inspected in the artifact view.",
      "voice": "Report the result",
      "worker": "Saved artifact"
    }
  ],
  "architecture": [
    {
      "title": "Separate people before interpretation.",
      "detail": "Zoom human tracks feed words and semantic completion in parallel."
    },
    {
      "title": "Route a complete thought.",
      "detail": "Align the final words. Gemini decides whether Sparkie was addressed."
    },
    {
      "title": "Speak, with human priority.",
      "detail": "Realtime voices the answer. Confirmed human speech takes priority over playback."
    },
    {
      "title": "Delegate, execute, report.",
      "detail": "A transcript snapshot reaches Devin; task results return to the voice."
    }
  ],
  "product": [
    {
      "title": "One workspace for the meeting.",
      "image": "assets/product/workspace.webp",
      "alt": "Actual Sparkie local voice workspace with transcript, tasks and the generated report.",
      "detail": "The conversation, delegated work and saved results stay together.",
      "label": "Workspace"
    },
    {
      "title": "The discussion stays in view.",
      "image": "assets/product/transcript.webp",
      "alt": "Saved transcript of a report request and Sparkie responses from a local voice session.",
      "detail": "Inspect the transcript behind a request. Keep the shared context visible.",
      "label": "Transcript"
    },
    {
      "title": "See what the worker is doing.",
      "image": "assets/product/tasks.webp",
      "alt": "Completed tasks and artifact catalog from a local voice session.",
      "detail": "Task status and tool events show activity. This capture shows completed work.",
      "label": "Tasks"
    },
    {
      "title": "Open the actual result.",
      "image": "assets/product/report.webp",
      "alt": "The generated About Sparkie report in the workspace artifact view.",
      "detail": "Read the artifact, then ask for an explicit follow-up edit.",
      "label": "Artifact"
    }
  ],
  "routing": [
    {
      "context": "The team is discussing a possible use for the assistant.",
      "utterance": "“Sparkie could help with this later.”",
      "decision": "quiet",
      "label": "Quiet · keep listening",
      "reason": "A third-person mention does not invite a reply."
    },
    {
      "context": "Sparkie has just compared two approaches for the team.",
      "utterance": "“Which one would you choose?”",
      "decision": "active",
      "label": "Active · respond to this turn",
      "reason": "The recent exchange makes this a follow-up, even without the name."
    },
    {
      "context": "Two teammates are speaking to each other; the recipient is unclear.",
      "utterance": "“Can you take care of that?”",
      "decision": "quiet",
      "label": "Quiet · keep listening",
      "reason": "Being able to help is not enough. An unclear recipient means no reply."
    }
  ]
};
Object.assign(window.SPARKIE_DECK, {slides: [
  {
    "title": "A teammate with the meeting context.",
    "chapter": "MOTIVATION",
    "seconds": 15,
    "notes": "We want an agent that is already part of the meeting. It follows the discussion, understands what a request refers to, and can handle work while the team keeps talking. Sparkie is our prototype of that teammate.",
    "cue": "Open with the goal. The photo is an editorial illustration, not a Sparkie session."
  },
  {
    "title": "Keep the context. Start the work.",
    "chapter": "MOTIVATION",
    "seconds": 35,
    "notes": "In a meeting, the useful context is spread across the conversation: the options we considered, the constraints, and what we decided. A separate chat makes someone explain it all again. We want to ask for a comparison, a file, or an edit right there in the discussion. The agent should participate when invited and work in the background while people continue. That is what we mean by a meeting agent with shared context.",
    "cue": "Emphasize shared conversation and work during the meeting. This is the product goal, not unlimited memory: the current system only receives the session input available after it joins; tasks receive a snapshot at delegation."
  },
  {
    "title": "Where Sparkie fits.",
    "chapter": "COMPETITIVE CONTEXT",
    "seconds": 50,
    "notes": "Granola focuses on meeting memory. We want a speaking participant as well. Vapi provides voice agents connected to tools; the shared-meeting behavior still needs to be built. ZoomMate already connects meeting context to workflows, so executing work is not unique to us. Our focus is the bridge from a shared meeting to an agent in our own project: its files, commands, and tools. The team keeps talking and can review the result together.",
    "cue": "Place this directly after motivation. Four comparisons: existing value, the specific bridge we built, then Sparkie. Do not claim competitors cannot execute work. Official sources are available in the source drawer."
  },
  {
    "title": "What we built.",
    "chapter": "THE PRODUCT",
    "seconds": 45,
    "notes": "Here is the actual frontend. The workspace brings the conversation, task center and artifacts together. The transcript makes the request inspectable. The task panel shows status and backend tool activity while the voice remains available. When the worker finishes, the result opens as an artifact that we can read and refine. These screenshots come from a completed local voice session. Next, we will show the supplied Zoom demo video.",
    "cue": "Four views: workspace, transcript, tasks, artifact. Click a capture to enlarge it. The task screenshot shows completed work; it is not a live progress feed. These captures are separate from the Zoom recording."
  },
  {
    "title": "Watch it in the meeting.",
    "chapter": "THE DEMO",
    "seconds": 60,
    "notes": "Now watch the meeting experience. Follow the spoken request, the background work, and the result the team can inspect. The important connection is that the discussion and the work happen in the same session.",
    "cue": "Play the supplied YouTube demo. The player uses the full recording; 60 seconds is a suggested talk allowance, not an automatic trim or a measured task duration. Let the actual clip establish what happened. The adjacent About Sparkie report comes from a separate local voice session."
  },
  {
    "title": "From conversation to action.",
    "chapter": "ARCHITECTURE",
    "seconds": 40,
    "notes": "Zoom supplies separate human audio tracks. Deepgram gives us the words, and Realtime semantic turn detection estimates when the thought is complete. Gemini makes the participation decision. An accepted turn reaches the foreground Realtime voice agent, which can delegate work to a separate Devin or Codex worker. Results return through the task center. The difficult part is the decision in the middle: should the agent speak at all?",
    "cue": "Four builds: input, routing, voice, worker. End on Gemini to introduce the dedicated next page. In this Zoom mode the foreground receives assembled text; separate Realtime sessions handle semantic audio completion."
  },
  {
    "title": "When should Sparkie speak?",
    "chapter": "THE MAIN CHALLENGE",
    "seconds": 65,
    "notes": "The hard part is deciding when to participate. A name match is not enough: people can talk about Sparkie without talking to it. The reverse also happens: “Which one would you choose?” can clearly be a follow-up without a name. We use Gemini as a dedicated, tool-free router. It sees the completed current utterance, the speaker identity, and up to eight recent human and assistant entries. It returns accept or reject. Accept lets the foreground voice respond to this turn. Reject keeps it quiet while listening continues. We reassess each turn; an earlier response is not permanent permission to talk. If the recipient is unclear, or routing fails, it stays quiet.",
    "cue": "This is the central technical page. Click Mention, Follow-up, and Ambiguous. Examples illustrate the implemented policy; they are not new live classifier measurements. Gemini decides participation, not speech endpoints or playback interruption. Confirmed human speech has a separate priority path that stops playback. The eight-entry router window is distinct from meeting context and task snapshots."
  },
  {
    "title": "Keep talking while work continues.",
    "chapter": "ARCHITECTURE",
    "seconds": 30,
    "notes": "The voice loop and the task worker run separately. The worker starts with the transcript snapshot available when the task is delegated. People can keep discussing and interrupt the voice without automatically cancelling that task. The result returns for review when ready. If the discussion changes the requirements, an explicit update carries that change into the work.",
    "cue": "Four beats: delegate, background work, voice interruption, result. The diagram explains control flow; its progress bar is not live telemetry or a latency measurement."
  },
  {
    "title": "What still needs work.",
    "chapter": "LIMITATIONS",
    "seconds": 35,
    "notes": "This is still a prototype. Setup is not one click: it needs the Zoom SDK, provider credentials, CLI login, and platform permissions. Our primary path is macOS Zoom with English speech. Wake decisions, turn boundaries and acoustic echo can still be wrong; latency varies across providers and tasks. Recovery after input failures is limited. And later decisions do not silently update a running task: we need an explicit follow-up.",
    "cue": "Be concrete about what is missing. No latency numbers without measurements. The agent processes meeting audio; it does not inspect participants’ screens or video."
  },
  {
    "title": "Easier to invite. More proactive.",
    "chapter": "OUTLOOK",
    "seconds": 25,
    "notes": "We want to take Sparkie in two directions. First, make it easier to use: guided setup, more reliable sessions, and task updates that are easy to follow. Second, make it more proactive. With the meeting context, it could spot useful work, suggest a next step, or offer to take on a task at the right moment. The goal is a teammate that helps move the meeting forward, while respecting the people in the room.",
    "cue": "Two directions on one slide: easier to use, and more proactive. Setup includes credentials and permissions; reliability includes recovery and participation evaluation. Proactive suggestions and offers are future work, beyond the current invitation-based routing policy. Close on the product goal, then take questions."
  }
]});
