# Sparkie Demo Video Outline

## Title
Sparkie: An AI Meeting Teammate That Follows, Answers, and Acts

## Goal
Show Sparkie working inside a real meeting first, then explain how it works. The demo makes the product concrete before introducing the architecture, and it clearly states what Sparkie can and cannot perceive.

## Audience
- Hackathon judges and visitors
- Potential collaborators and early testers
- Teammates joining the next build

## Overall Structure
1. **Sparkie in action** — join, listen, wake, answer, summarize, and carry out a file task while the conversation continues.
2. **How it works** — a short architecture walkthrough with on-screen diagram.

---

## Scene Breakdown

### 0:00–0:15 — Hook: a meeting that needs help
- **Narration:** “Meetings move fast. Ideas get lost, questions go unanswered, and someone still has to take notes. This is Sparkie — an AI teammate that sits in the meeting with you.”
- **On screen:** Two or three people on a Zoom call, mid-conversation. Lower-third title card: “Sparkie — AI meeting teammate.”
- **Editing notes:** Start on a real human moment, not on code. Use clean title card, no sound effects.

### 0:15–0:40 — Sparkie joins and listens
- **Narration:** “Sparkie joins just like any other participant. While the team talks, it follows the conversation from audio and transcripts.”
- **On screen:** Split screen — Zoom meeting on the left, Sparkie transcript/event panel on the right. Captions appear as people speak.
- **Editing notes:** Keep the Zoom tile and the transcript panel in the same shot. Highlight the latest final transcript line.

### 0:40–1:05 — Wake on name and answer a question
- **Narration:** “Say its name, and it wakes up. ‘Sparkie, what did we decide about the launch date?’”
- **On screen:** Participant asks the question; transcript highlights the wake word; Sparkie’s reply text and audio waveform appear.
- **Editing notes:** Use a subtle highlight or zoom on the wake-word transcript. Show the reply event in the panel as audio plays.

### 1:05–1:25 — Clarify and bring the discussion back
- **Narration:** “If the conversation drifts, Sparkie can bring it back on track or clarify a point.”
- **On screen:** Team goes off-topic; participant says, “Sparkie, what were we discussing?” Sparkie replies with the current topic summary.
- **Editing notes:** Keep cuts tight. Show before/after side-by-side transcript snippets.

### 1:25–1:55 — Work on a file while the meeting continues
- **Narration:** “Best of all, Sparkie can keep working while you keep talking. Here, it drafts a summary document based on what it heard.”
- **On screen:** Conversation continues on the left; on the right, Sparkie writes into a Markdown file. The file content updates in real time.
- **Editing notes:** Speed up the typing if needed, but keep the audio natural. End with the saved file path shown.

### 1:55–2:25 — How it works
- **Narration:** “Sparkie is software, not a person. It only knows the audio, transcripts, context, and tool results supplied to this session. It cannot see cameras, private screens, or meetings it is not in.”
- **On screen:** Simple architecture diagram — Zoom Meeting SDK → Deepgram STT → GPT Realtime voice/agent → Deepgram/Aura TTS and background task worker. Arrows show audio and transcript flow.
- **Editing notes:** Use a clean diagram, not code. Animate arrows sequentially. Add labels for each component.

### 2:25–2:45 — Capabilities and current boundaries
- **Narration:** “Sparkie follows conversation, answers questions, clarifies ideas, summarizes discussion, and helps research, create documents, and carry out requested tasks. It does not send email, process video, proactively interrupt, or perform precise diarization — those are the next milestones.”
- **On screen:** Bulleted capability list appears next to a short boundary list. Show the offline fallback `scripts/demo.sh` as a runnable simulation.
- **Editing notes:** Keep text readable; avoid overclaiming words like “always” or “perfectly.”

### 2:45–3:00 — Closing
- **Narration:** “Sparkie makes the meeting useful after it ends — because the teammate was already paying attention.”
- **On screen:** Final shot of the meeting with Sparkie present, followed by a title card with the project name and repository.
- **Editing notes:** End on the live meeting shot; fade to title card.

---

## Production Notes

- **Primary take:** real Zoom join → live transcript → wake → answer → clarify → file task.
- **Fallback take:** clearly labeled offline simulation using `bash scripts/demo.sh` plus `sparkie tts` / `sparkie deepgram-check` if live join is unstable.
- **Audio:** record clean meeting audio and narrator voiceover separately when possible.
- **Captions:** add lower-thirds for each beat — Join, Listen, Wake, Answer, Clarify, Act, How It Works, Boundaries.
- **Length target:** 2–3 minutes for the pitch version; 4–5 minutes for a technical walkthrough.

## Roles (from team discussion)

| Role | Owner | Responsibility |
| --- | --- | --- |
| Narration and flow | Hanhong Zhao | Handle the intro and guide the demo narration. |
| Recording | Yifan Kang | Record the Zoom meeting feed and the Sparkie task panel. |
| Review and edit | Bowen Yu | Receive the recording, review the result, and edit the final demo. |

### Reviewer checklist

- Verify that every claim in the narration matches what is actually shown on screen.
- Confirm the timing fits the target length.
- Confirm captions, titles, and lower-thirds are consistent and correctly placed.
- Check audio quality and transitions between scenes.

## Important Disclaimer

Sparkie is software, not a human participant. It only has access to the audio, transcripts, context, and tool outputs provided in the current session. It cannot implicitly see cameras, shared screens, or private meetings it has not joined.
