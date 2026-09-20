"""Command-line entry points for Realtime voice and meeting workspaces."""
import argparse
import asyncio
import os
import platform
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from .providers import ProviderError
from .zoom_config import selected_platform, sdk_path, sdk_present


def doctor():
    checks = {}
    for name in ["DEEPGRAM_API_KEY", "OPENAI_API_KEY",
                 "ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET", "ZOOM_MEETING_ID", "ZOOM_MEETING_PASSWORD"]:
        checks[name] = bool(os.getenv(name))
    try:
        target = selected_platform()
    except ValueError as error:
        print(str(error))
        return 1
    checks["ZOOM_SDK_FILES"] = sdk_present(target, sdk_path(target))
    if target == "macos":
        checks["MACOS_HOST"] = platform.system() == "Darwin"
        checks["XCODE_AVAILABLE"] = False
        if checks["MACOS_HOST"] and shutil.which("xcodebuild"):
            try:
                checks["XCODE_AVAILABLE"] = subprocess.run(
                    ["xcodebuild", "-version"], stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=10).returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                pass
    else:
        checks["DOCKER_RUNNING"] = False
        if shutil.which("docker"):
            try:
                checks["DOCKER_RUNNING"] = subprocess.run(
                    ["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
                ).returncode == 0
            except (subprocess.TimeoutExpired, OSError):
                pass
    for name, present in checks.items():
        print(f"{'OK     ' if present else 'MISSING'} {name}")
    backend = os.getenv('SPARKIE_TASK_BACKEND') or 'codex'
    checks['TASK_CLI'] = shutil.which(backend) is not None
    print(f"Task backend: {backend}; CLI: {'found' if checks['TASK_CLI'] else 'missing'}")
    print(f"Zoom platform: {target}; host architecture: {platform.machine()}; SDK must match its runtime architecture.")
    print("Presence check only; this does not authenticate keys, verify SDK compatibility or join Zoom.")
    return 0 if all(checks.values()) else 1


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Sparkie meeting assistant")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check local configuration without calling APIs")
    sub.add_parser("devices", help="List microphone and speaker devices without recording")
    for name, seconds in (("local", 120), ("zoom", 600)):
        voice = sub.add_parser(name, help=f"Start a {name} Realtime voice session")
        voice.add_argument("--language", choices=["en-US", "en", "zh-CN"],
                           default=os.getenv("DEEPGRAM_LANGUAGE") or "en-US")
        voice.add_argument("--seconds", type=int, default=seconds)
        voice.add_argument("--output", type=Path, default=Path("output") / name)
        voice.set_defaults(transport=name)
        if name == "local":
            voice.add_argument("--input-device", default=os.getenv("SPARKIE_INPUT_DEVICE"))
            voice.add_argument("--output-device", default=os.getenv("SPARKIE_OUTPUT_DEVICE"))
            voice.add_argument("--echo-mode", choices=["speaker", "headphones"], default="speaker")
    workspace = sub.add_parser("workspace", help="Serve meeting workspaces over HTTP and WebSocket")
    workspace.add_argument("--host", default="127.0.0.1")
    workspace.add_argument("--port", type=int, default=8790)
    workspace.add_argument("--db", type=Path, default=Path("output/workspace.db"))
    workspace.add_argument("--worker", choices=["codex", "devin", "demo"],
                           default=os.getenv("SPARKIE_TASK_BACKEND") or "codex",
                           help="demo produces simulated artifacts without a model")
    args = parser.parse_args()
    if args.command == "doctor":
        raise SystemExit(doctor())
    if args.command == "devices":
        from .local_audio import list_devices
        raise SystemExit(list_devices())
    if args.command == "workspace":
        from .workspace_server import workspace_session as command
    else:
        if not 1 <= args.seconds <= 3600:
            parser.error("--seconds must be between 1 and 3600")
        from .realtime_session import run as command
    try:
        raise SystemExit(asyncio.run(command(args)))
    except (ProviderError, ValueError, TimeoutError) as exc:
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
