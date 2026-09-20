"""Drive a scripted English demo dialogue into the workspace pipeline.

Feeds scripted utterances over the WS event socket exactly like the browser's
simulate form, so the heuristic runtime routes them (wake -> RESPOND, research
keywords -> CREATE_TASK against the configured worker, "show us" -> PRESENT).
Prints every broadcast event and finishes with the produced artifacts.

Usage:
    uv run --frozen python scripts/workspace_demo.py [--server 127.0.0.1:8790]
        [--meeting demo-video] [--delay 1.2] [--timeout 600]
"""
import argparse
import asyncio
import json
import urllib.parse
import urllib.request

import httpx
from websockets.asyncio.client import connect

# The wake word must open the utterance (ADDRESS is anchored); these lines keep
# "Sparkie" first so the heuristic routes them like real addressed speech.
SCRIPT = [
    ("Yifan", "Hey everyone, thanks for joining. Today we are reviewing Sparkie, "
              "our real-time meeting participant."),
    ("Bowen", "Quick question before we dive in — is it actually listening?"),
    ("Yifan", "Sparkie, are you there?"),
    ("Bowen", "Sparkie, research which products already do real-time AI meeting "
              "participation, like Otter, Read AI and Zoom AI Companion, and how "
              "we differ. Keep it short, Markdown."),
    ("Yifan", "Sparkie, look up the current weather in Boston and tell me if I "
              "need a jacket tonight."),
    # Hold until running tasks finish so "show us" actually has an artifact.
    (None, "__WAIT_TASKS__"),
    ("Bowen", "Sparkie, show us what you found."),
    ("Yifan", "Sparkie, draft a Markdown document listing five concrete next "
              "steps for Sparkie, each with a one-line rationale."),
    ("Yifan", "Alright, that is the demo. Thanks everyone."),
]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="127.0.0.1:8790")
    parser.add_argument("--meeting", default="demo-video")
    parser.add_argument("--delay", type=float, default=1.2,
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
        print(f"  task {task['task_id']}: {task['status']} — {task['instruction'][:60]}")
    for artifact in snapshot_data["artifacts"]:
        print(f"  artifact {artifact['artifact_id']}: {artifact['title']!r} "
              f"({artifact['status']})")
        content = artifact.get("content") or {}
        markdown = content.get("markdown")
        if markdown:
            print("    --- first 15 lines ---")
            for line in markdown.splitlines()[:15]:
                print(f"    {line}")


if __name__ == "__main__":
    asyncio.run(main())
