"""Replay the recorded-demo script (sparkie-demo-script.html) into the workspace.

Feeds the nine-scene rehearsal dialogue over the WS event socket so the
heuristic runtime routes addressed lines: questions -> RESPOND, document
requests -> CREATE_TASK against the configured worker, "show us" -> PRESENT.
The outline task and the roles-append task both hit the real worker; the
script waits for each before continuing, matching the script's gates.

Usage:
    uv run --frozen python scripts/demo_rehearsal.py [--server 127.0.0.1:8790]
        [--meeting demo-rehearsal] [--delay 1.5] [--timeout 600]
"""
import argparse
import asyncio
import json
import urllib.parse
import urllib.request

import httpx
from websockets.asyncio.client import connect

# Spoken lines from sparkie-demo-script.html v3, scene by scene. Wake word stays
# at the head of addressed lines (ADDRESS is anchored). __WAIT_TASKS__ marks the
# script's "outline must really be done" gates.
SCRIPT = [
    # 1. opening — Sparkie stays silent
    ("Hope", "Okay, let's figure out how to show Sparkie. It's in the meeting "
             "with us, so let's plan the demo together."),
    # 2. discussion — two openers, no wake word
    ("Yifan", "I'd start with the architecture, so people understand how it works."),
    ("Bowen", "I'd rather open on a real meeting. Let people see it do something useful."),
    ("Hope", "Most viewers won't know what Sparkie is. We need to make the value obvious."),
    # 3. context — did it hear the whole discussion?
    ("Hope", "Sparkie, which idea do you prefer?"),
    # 4. delegate — real file task
    ("Hope", "Let's do the meeting first, then a quick look at how it works."),
    ("Bowen", "So we need someone to walk viewers through it, someone to record "
              "the meeting and the task, and someone to show the result and "
              "edit the video."),
    ("Yifan", "Sparkie, can you turn that into a video outline? Include what we "
              "say and what we show, and save it as demo-outline.md in the project."),
    # 5. parallel — roles claimed while the outline runs
    ("Hope", "While that's running, I can handle the intro and walk people "
             "through what's happening."),
    ("Yifan", "I'll record the meeting and the task panel, so we can show it "
              "working while we talk."),
    ("Bowen", "Then I'll show the finished result and edit everything together."),
    (None, "__WAIT_TASKS__"),
    # 6. result — report, then present it
    ("Bowen", "Sparkie, how's the outline looking?"),
    ("Bowen", "Sparkie, show us the outline."),
    ("Hope", "That's the flow we had in mind."),
    # 7. roles review — connect the split to the outline
    ("Hope", "Sparkie, does that split make sense for this outline, or are we "
             "missing anything?"),
    ("Hope", "Sounds good. I'll take the narration."),
    ("Yifan", "I'll send the screen recording over for the edit."),
    ("Bowen", "And I'll handle the result and the final cut."),
    # 8. save roles — append to the same file
    ("Hope", "Sparkie, add the roles we just agreed on to the end of the "
             "outline, so everything's in one place."),
    (None, "__WAIT_TASKS__"),
    # 9. closing
    ("Bowen", "There we go. What we're filming, and who's doing each part."),
    ("Hope", "Great. Let's record it."),
]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="127.0.0.1:8790")
    parser.add_argument("--meeting", default="demo-rehearsal")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="seconds between scripted utterances")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()

    query = urllib.parse.urlencode({
        "kind": "zoom_uuid", "external_id": args.meeting,
        "title": "Sparkie demo rehearsal", "reset": "1"})
    async with httpx.AsyncClient(timeout=5) as http:
        workspace = (await http.get(
            f"http://{args.server}/api/meetings/resolve?{query}")).json()
    ws_id = workspace["workspace_id"]
    print(f"[workspace] {ws_id} ({args.meeting})", flush=True)

    url = f"ws://{args.server}/workspaces/{ws_id}/events"
    async with connect(url) as socket:
        async def listen():
            try:
                async for raw in socket:
                    event = json.loads(raw)
                    keep = {"utterance", "agent.respond", "task.updated",
                            "task.started", "task.completed", "task.failed",
                            "task.cancelled", "artifact.ready",
                            "artifact.present", "meeting.ended",
                            "workspace.reset"}
                    if event.get("type") in keep:
                        print(f"[event] {json.dumps(event, ensure_ascii=False)}",
                              flush=True)
            except Exception as exc:
                print(f"[listener stopped] {exc}", flush=True)

        listener = asyncio.create_task(listen())

        async def snapshot():
            return await asyncio.to_thread(
                lambda: json.loads(urllib.request.urlopen(
                    f"http://{args.server}/api/workspaces/{ws_id}").read()))

        async def wait_tasks():
            deadline = asyncio.get_running_loop().time() + args.timeout
            while asyncio.get_running_loop().time() < deadline:
                tasks = (await snapshot())["tasks"]
                if tasks and all(t["status"] in ("completed", "failed", "cancelled")
                                 for t in tasks):
                    return
                await asyncio.sleep(5)

        for speaker, text in SCRIPT:
            if text == "__WAIT_TASKS__":
                print("[wait] tasks settling…", flush=True)
                await wait_tasks()
                continue
            await socket.send(json.dumps(
                {"type": "utterance", "speaker": speaker, "text": text}))
            print(f"[say] {speaker}: {text[:80]}", flush=True)
            await asyncio.sleep(args.delay)

        await wait_tasks()
        await socket.send(json.dumps({"type": "end_meeting"}))
        await asyncio.sleep(3)
        await wait_tasks()
        snapshot_data = await snapshot()
        listener.cancel()

    print("\n[final snapshot]")
    for task in snapshot_data["tasks"]:
        print(f"  task {task['task_id']}: {task['status']} — {task['instruction'][:70]}")
    for artifact in snapshot_data["artifacts"]:
        print(f"  artifact {artifact['artifact_id']}: {artifact['title']!r} "
              f"({artifact['status']})")
        markdown = (artifact.get("content") or {}).get("markdown")
        if markdown:
            print("    --- first 15 lines ---")
            for line in markdown.splitlines()[:15]:
                print(f"    {line}")


if __name__ == "__main__":
    asyncio.run(main())
