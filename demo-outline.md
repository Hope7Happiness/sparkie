# Sparkie Hackathon Demo Outline

**Target length:** 75–90 seconds

## 1. Open in the meeting (0:00–0:10)

**Show:** A live Zoom-style meeting with Sparkie visible as a quiet participant. Two teammates are deciding how to position their product.

**Say (presenter):** “We’re building Sparkie: an AI teammate that joins the meeting, stays quiet, and helps only when you ask.”

## 2. Wake and delegate (0:10–0:32)

**Show:** The team continues its discussion. A teammate speaks directly to Sparkie; a small task-status indicator changes to `queued`.

**Say (teammate):** “Sparkie, compare the public voice meeting agents and tell us how to position this.”

**Say (Sparkie):** “It’s queued. I’ll bring back the key differences while you keep talking.”

## 3. Let the meeting continue (0:32–0:48)

**Show:** Sparkie remains silent while the humans continue discussing the demo. Briefly show live transcript/context and the background task moving from `queued` to `running`.

**Say (presenter):** “The meeting doesn’t pause. Sparkie keeps the context and delegates the longer work in the background.”

## 4. Deliver a decision-ready result (0:48–1:05)

**Show:** The task completes. Sparkie returns a compact spoken result plus a three-line result card.

**Say (Sparkie):** “Main result: position Sparkie as the quiet, explicitly invoked in-meeting teammate. It acknowledges by voice, delegates work without interrupting, and returns a short decision-ready answer.”

**Say (teammate):** “Great—let’s lead our demo with that flow.”

## 5. Quick architecture reveal (1:05–1:25)

**Show:** A simple animated diagram:

```text
Zoom meeting audio
  → transcript + explicit wake
  → foreground voice agent
  → background task worker
  → concise spoken result in the meeting
```

**Say (presenter):** “Under the hood, Sparkie turns meeting audio into context, handles the explicit wake in real time, delegates complex work, and brings the result back to the room.”

## 6. Close (1:25–1:30)

**Show:** Return to the meeting with Sparkie present and the final decision visible.

**Say (presenter):** “Sparkie: a teammate that listens quietly, works in the background, and speaks when it helps the team decide—so meetings moved work forward.”
