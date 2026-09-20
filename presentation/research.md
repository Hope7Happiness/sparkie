# Sparkie: product landscape and presentation evidence

Reviewed **September 20, 2026**, against official public product pages and this repository. These are product descriptions, not independent performance benchmarks. Website positioning and branding can change. No latency, accuracy, revenue, or time-saving statistics are used in the presentation.

## The positioning

**A teammate inside the meeting, with hands on the project.**

Sparkie combines shared meeting context, explicit spoken delegation, asynchronous project work, and a spoken return path. The story is about that interaction loop. It is not a claim that competitors only take notes, cannot use tools, or cannot join meetings.

Three useful, overlapping centers of gravity:

- **Remember:** meeting knowledge, notes, synthesis, preparation, and follow-through.
- **Converse:** voice interactions that advance a business workflow.
- **Execute:** workplace context connected to tools and deliverables.

Sparkie explores the combination in a multi-person Zoom meeting: discuss → address the agent → work in a project → inspect a result → explicitly request a revision.

## Official product research

| Product and official source | Published use cases observed | Relevance to Sparkie |
| --- | --- | --- |
| [Granola](https://www.granola.ai/) | Meeting notes, context across meetings, pre-meeting briefs, follow-ups and project-plan drafts. The page describes computer-audio capture without a meeting bot. | Strong adjacent experience for turning discussion into useful context. Sparkie explicitly occupies a participant seat and responds by voice. |
| [Otter](https://otter.ai/) | Meeting transcripts, summaries, decisions/action items, CRM connections, and sales/recruiting agent use cases. | Meeting intelligence already extends into workflows. Do not present Otter as transcription alone. |
| [Fireflies](https://fireflies.ai/) | Meeting capture and analysis, follow-up drafts, CRM updates, project-task creation, and MCP access to meeting knowledge. | Capture and downstream execution overlap. Sparkie emphasizes iterative spoken delegation into the active project. |
| [Vapi](https://vapi.ai/) | A builder platform for voice agents; the page exposes support, lead qualification, and appointment scheduling examples. | Voice can carry out work, rather than merely answer questions. Sparkie's current product surface is a shared meeting. |
| [Retell](https://www.retellai.com/) | Phone/contact-center agents, appointment booking, qualification, system updates, and human escalation. | Strong precedent for voice-to-action workflows. Sparkie explores team collaboration rather than a packaged phone workflow. |
| [ElevenLabs Agents](https://elevenlabs.io/agents) | Conversational agents, tools and workflows for support, sales and operations across voice and other channels. | Voice orchestration and tool use are established categories. Sparkie's differentiating focus is how they compose inside a working team meeting. |
| [Zoom AI-assistant product page](https://www.zoom.com/en/products/ai-assistant/) | The retrieved page is branded **ZoomMate**, with research, documents/decks, task delegation, routines, memory and connected workplace workflows. | Direct overlap with the vision of conversations becoming deliverables. Sparkie is an inspectable prototype in a developer-controlled project; no claim of unique agentic execution. |

Short excerpts supporting the categories:

- Granola: “Notes, actions and memory. Without a meeting bot.”
- Otter: “Automate the action items.”
- Vapi: “Customer Support”, “Lead Qualification”, “Appointment Scheduling”.
- Retell describes “booking appointments or updating systems”.
- Zoom: “Turn inspired discussions into impressive deliverables.”

All links were fetched during research. The comparison is deliberately qualitative. It does not assert that omitted features are absent, nor that vendor marketing claims have been independently validated.

## What the repository supports

The review covered the application and provider adapters, native Zoom bridge, workspace frontend/server, task execution, simulations, tests and operational documentation. The core product narrative follows the documented macOS Zoom path, not a mock session or a proposed integration.

| Presentation claim | Repository evidence | Boundary |
| --- | --- | --- |
| Sparkie joins a real Zoom meeting | [README](../README.md), [macOS Zoom guide](../docs/zoom-macos.md), [platform validation](../docs/platform-validation.md), native bridge under [native](../native/) | The demonstrated path is macOS Zoom. Linux, local audio, browser audio and simulations existing in the repo do not prove equivalent real-session behavior. |
| Separate human tracks provide context | [Participant STT](../src/sparkie/participant_stt.py), [Zoom input](../src/sparkie/zoom_audio.py), [Realtime Zoom audio](../src/sparkie/realtime_zoom_audio.py) | Excludes the bot's SDK track. Sound played on human speakers can still reenter through a human microphone. |
| A pause need not end a request | [Semantic turn detection](../docs/semantic-turn-detection.md), [semantic turns adapter](../src/sparkie/semantic_turns.py) | Separate per-participant Realtime semantic detectors; medium eagerness in the current setup. Probabilistic, not a guaranteed endpoint. |
| Completed turns are routed semantically | [Wake-router research](../docs/fast-wake-router-research.md), [wake router](../src/sparkie/wake_router.py), [Realtime session](../src/sparkie/realtime_session.py) | The current configured experiment uses Gemini 3.5 Flash Minimal through a separate tool-free Devin ACP process. Calling the agent by name is not alone proof it should reply. |
| Human speech can interrupt playback | [Realtime session](../src/sparkie/realtime_session.py), [Realtime Zoom audio](../src/sparkie/realtime_zoom_audio.py), [semantic turn notes](../docs/semantic-turn-detection.md) | Speech activity can pause playback; absent confirming text, a 350ms candidate window allows buffered audio to resume. Confirmed speech cancels the current reply. No perfect speaker-echo rejection claim. |
| Voice and tools run separately | [Realtime](../src/sparkie/realtime.py), [task center](../src/sparkie/task_center.py), [task workers](../src/sparkie/task_workers.py), [Devin ACP](../src/sparkie/devin_acp.py) | GPT Realtime is foreground voice. Devin SWE 1.6 Fast is the current background worker, with Codex selectable. Files, shell, network and configured tools run in the project. |
| The team can refine a saved result | [README](../README.md), [demo shooting script](../docs/sparkie-demo-script.html), [task center](../src/sparkie/task_center.py) | The task starts with finalized context at delegation. Later decisions need an explicit update or follow-up. An acknowledgement is not a successful task result. Inspect the file. |
| Providers can change without changing the meeting contract | [Contracts](../src/sparkie/contracts.py), [interfaces](../docs/interfaces.md) | A separation of implementation responsibilities, not a promise of identical behavior across providers. |

In this mode, complete assembled text reaches the foreground voice session. Audio is also sent to separate per-participant Realtime sessions for semantic turn completion. Avoid a diagram that implies a single undifferentiated model receives all audio and independently runs all tools.

## Broader use-case map

The six interactive scenes are **possibilities**, not six additional validated integrations. “Imagine” is deliberately visible beside the possible result.

| Room | Moment worth acting on | Possible delegated work | Review or integration boundary |
| --- | --- | --- | --- |
| Product review | The team chooses a direction | Turn the discussion into a brief, alternatives table or first spec | Team checks scope and decisions. No invented owners or deadlines. |
| Engineering | A failure or tradeoff becomes concrete | Inspect the repository, compare designs, draft a fix or test plan | Repository access and human code review; no implied production deployment. |
| Research | Two claims need evidence | Find sources, compare findings, draft a sourced memo | Verify citations and source quality. Web access/tool configuration is required. |
| Customer call | Priorities become clear | Draft a tailored follow-up, proposal outline or requirements summary | A draft, not an email silently sent to a customer. CRM integration requires actual tools/access. |
| Hiring debrief | Interviewers compare observations | Organize notes against an agreed rubric and identify missing evidence | Human review; not automated hiring decisions or inferred sensitive traits. |
| Launch planning | A dependency or plan changes | Update a project checklist or draft a rollout brief | Explicit updates; no automatic assignment of people, dates or external project tickets. |

Additional rooms for Q&A: a design critique leading to a revision brief; an incident review producing a draft timeline; a workshop synthesizing questions into a research agenda; a weekly review updating a project document. These extend the same loop. They are not new native connectors or independently tested workflows.

## Evidence for the demo slot

The actual product loop is documented in the README and the existing shooting script: three teammates plan a demo film, ask Sparkie for an outline, keep discussing filming, open the real output, and ask it to incorporate the agreed roles.

The presentation contains **illustrated placeholders**, not a recording or a fabricated result. Add a real session excerpt and a real artifact screenshot before presenting it as evidence. If an edit shortens a wait, label that edit in the recording. A human opens and shares the file; Sparkie is not claimed to understand video or autonomously share its screen.

User feedback accepted the current medium semantic-turn setting and audible responses in real sessions. That is qualitative feedback, not a latency benchmark. This presentation makes no universal accuracy, long-session reliability, multilingual voice, enterprise deployment, or unattended external-action claim.

## Visual and interaction references

- [Chrome: Smooth transitions with the View Transition API](https://developer.chrome.com/docs/web-platform/view-transitions). Shared element snapshots support continuity between distinct layouts. Used for circles, the Sparkie mark and artifact panels across slides, with a reduced-motion and unsupported-browser fallback.
- [Codrops: Vivid — Turning a Visual Experiment Into an Interactive Webflow Experience](https://tympanus.net/codrops/2026/09/15/vivid-turning-a-visual-experiment-into-an-interactive-webflow-experience/). The article explains state-to-state visual navigation and transitions as part of the experience. The deck uses explicit scene navigation; the homepage preserves ordinary document scrolling.
- [Awwwards: Animation websites](https://www.awwwards.com/websites/animation/). A surveyed inspiration index for expressive web motion, not a source for product claims.

The art, SVGs, layout and animation implementation here are original repository assets. No third-party site assets, fonts, animation libraries or tracking scripts are loaded. The product icon is reused from this repository.
