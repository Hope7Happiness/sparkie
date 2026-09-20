# Sparkie Demo Video Outline

**Structure:** real meeting first, then a quick look at how it works.  
**Target length:** ~75–90 seconds.

## Roles

- **Presenter / narrator** — walks viewers through the demo, speaks the on-screen framing, and bridges each segment.
- **Recorder** — records the real meeting and the task panel as it moves from `queued` to `running` to `completed`.
- **Results & video editor** — shows the final result, prepares the decision-ready card, and edits the video.

## 1. Open in a real meeting (0:00–0:15)

**Show:** A live Zoom-style meeting with Sparkie present as a quiet participant. Two teammates are discussing how to demo Sparkie.

**Say (presenter):** “We’re building Sparkie, an AI teammate that joins your meeting, listens quietly, and helps when you ask.”

## 2. Wake and delegate (0:15–0:35)

**Show:** One teammate says “Sparkie” and asks a useful question; the visible task panel switches to `queued`.

**Say (teammate):** “Sparkie, compare public voice meeting agents and tell us how to position this.”

**Say (Sparkie):** “I’m on it. I’ll bring back the key differences while you keep talking.”

## 3. Meeting continues in the background (0:35–0:55)

**Show:** The humans keep talking; brief cut to the task panel moving from `queued` to `running`.

**Say (presenter):** “The meeting keeps going. Sparkie holds the context and delegates the longer work to a background agent.”

## 4. Result comes back (0:55–1:15)

**Show:** The task panel reaches `completed`. Sparkie speaks a short result and a concise result card appears.

**Say (Sparkie):** “Main result: position Sparkie as the quiet, explicitly-invoked teammate. It acknowledges by voice, delegates work without interrupting, and returns a short decision-ready answer.”

**Say (teammate):** “Great—let’s lead the demo with that flow.”

## 5. Quick look at how it works (1:15–1:30)

**Show:** A simple architecture diagram:

```text
Zoom meeting audio
  → transcript + explicit wake
  → foreground voice agent
  → background task worker
  → concise spoken result in the meeting
```

**Say (presenter):** “Under the hood, Sparkie turns meeting audio into context, handles the wake in real time, delegates the task, and brings the answer back to the room.”

## 6. Close (1:30–1:40)

**Show:** Return to the meeting with Sparkie present and the final decision visible.

**Say (presenter):** “Sparkie: a teammate that listens quietly, works in the background, and speaks when it helps the team decide—so meetings move work forward.”
