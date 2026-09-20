import argparse
import asyncio
import json
import os
import platform
import shutil
import subprocess
import wave
from pathlib import Path

from dotenv import load_dotenv

from .contracts import TranscriptEvent
from .engine import Primitive
from .simulation import ScriptedDeepgram, SimulatedSpeech, SimulatedMeeting
from .providers import DeepgramMouth, DeepgramEars, ProviderError
from .audio import AudioFrame
from .backends import configured_brain
from .zoom_config import selected_platform, sdk_path, sdk_present


def doctor():
    checks = {}
    for name in ["DEEPGRAM_API_KEY", "DEEPGRAM_TTS_MODEL",
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
    for name in ["OPENAI_API_KEY", "OPENAI_MODEL"]:
        print(f"{'SET' if os.getenv(name) else 'OPTIONAL'} {name} (not needed for fixed reply)")
    print(f"Backend: {os.getenv('SPARKIE_BACKEND') or 'codex'}; Codex CLI: {'found' if shutil.which('codex') else 'missing'}")
    print(f"Zoom platform: {target}; host architecture: {platform.machine()}; SDK must match its runtime architecture.")
    print("Presence check only; this does not authenticate keys, verify SDK compatibility or join Zoom.")
    return 0 if all(checks.values()) else 1


async def simulate(args):
    events = [TranscriptEvent(**json.loads(line)) for line in args.input.read_text().splitlines() if line.strip()]
    if not events:
        raise ValueError("Fixture must contain at least one event")
    if len({e.meeting_id for e in events}) != 1:
        raise ValueError("Primitive accepts one meeting per run")
    live_tts = args.tts == "deepgram"
    meeting = SimulatedMeeting(events, args.output, interval=args.interval,
                               audio_prefix="deepgram-reply" if live_tts else "simulated-reply")
    mouth = configured_mouth() if live_tts else SimulatedSpeech()
    primitive = Primitive(meeting, ScriptedDeepgram(events), mouth,
                          reply=os.getenv("SPARKIE_REPLY") or "I'm here.",
                          mode="hybrid-tts" if live_tts else "simulate")
    result = await primitive.run()
    result["inputs_while_playing"] = meeting.inputs_while_playing
    result["audio_files"] = meeting.outputs
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "run.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for event in result["events"]:
        if event["type"] in {"wake", "reply", "response_cancelled", "response_failed"}:
            print(json.dumps(event, ensure_ascii=False))
    audio_kind = "real Deepgram speech" if live_tts else "silent mock audio"
    print(f"{result['mode']}: {len(meeting.outputs)} WAV output(s) ({audio_kind}); {meeting.inputs_while_playing} input(s) during simulated playback → {path}")
    print("Zoom and STT are simulated. Deepgram TTS was called." if live_tts else "No Zoom connection or external API request was made.")
    return 1 if result["response_failures"] else 0


def configured_mouth():
    key = os.getenv("DEEPGRAM_API_KEY")
    if not key:
        raise ValueError("Set DEEPGRAM_API_KEY in .env first")
    return DeepgramMouth(key, os.getenv("DEEPGRAM_TTS_MODEL") or "aura-2-thalia-en")


def save_wav(path, pcm):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(32000)
        wav.writeframes(pcm)


async def tts(args):
    pcm = await configured_mouth().synthesize(args.text or os.getenv("SPARKIE_REPLY") or "I'm here.")
    save_wav(args.output, pcm)
    print(f"LIVE Deepgram TTS: {len(pcm) / 64000:.2f}s PCM16 mono 32kHz → {args.output}")
    return 0


async def deepgram_check(args):
    # Known synthetic English speech only: no microphone or meeting content is uploaded.
    pcm = await configured_mouth().synthesize("Sparkie, are you there?")
    save_wav(args.output / "probe.wav", pcm)
    async def frames():
        padded = pcm + b"\0" * 64000  # One second of trailing silence for endpointing.
        for sequence, offset in enumerate(range(0, len(padded), 1280)):
            yield AudioFrame(sequence, padded[offset:offset + 1280])
            await asyncio.sleep(.02)
    ears = DeepgramEars(os.environ["DEEPGRAM_API_KEY"], "deepgram-check",
                        model=os.getenv("DEEPGRAM_MODEL") or "nova-3", language="en-US")
    events = []
    async with asyncio.timeout(30):
        async for event in ears.transcribe(frames()):
            events.append(event)
    transcript = " ".join(e.text for e in events)
    from .wake import addressed_request
    passed = addressed_request(transcript) is not None
    report = {"mode": "live-deepgram-check", "tts_model": configured_mouth().model,
              "stt_model": ears.model, "stt_language": "en-US", "transcript": transcript,
              "wake_detected": passed, "audio_seconds": len(pcm) / 64000,
              "zoom_tested": False}
    (args.output / "check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    if not passed:
        raise ProviderError("Deepgram check did not produce a recognizable wake request; inspect output transcript")
    return 0


async def brain_check(args):
    backend = args.backend or os.getenv("SPARKIE_BACKEND") or "codex"
    brain = configured_brain(backend)
    answer = await brain.answer(["We decided to use Zoom for the meeting and Deepgram for speech recognition and synthesis.",
                                 "Sparkie, which services did we choose?"])
    print(json.dumps({"backend": backend, "answer": answer, "zoom_tested": False}, ensure_ascii=False))
    return 0


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Sparkie Phase 0; simulate needs no keys or network")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check local configuration without revealing secrets or calling APIs")
    sim = sub.add_parser("simulate", help="Offline meeting → scripted STT → wake → silent mock audio")
    sim.add_argument("--input", type=Path, default=Path("examples/primitive.jsonl"))
    sim.add_argument("--output", type=Path, default=Path("output/primitive"))
    sim.add_argument("--interval", type=float, default=0.08)
    sim.add_argument("--tts", choices=["mock", "deepgram"], default="mock", help="deepgram makes a real TTS request; meeting/STT remain simulated")
    speech = sub.add_parser("tts", help="Generate a WAV using the configured live Deepgram key")
    speech.add_argument("--text")
    speech.add_argument("--output", type=Path, default=Path("output/deepgram/reply.wav"))
    check = sub.add_parser("deepgram-check", help="Live synthetic TTS → streaming STT check; uses a small amount of API quota")
    check.add_argument("--output", type=Path, default=Path("output/deepgram"))
    brain = sub.add_parser("brain-check", help="Check the configured live reasoning backend with synthetic meeting text")
    brain.add_argument("--backend", choices=["codex", "openai"])
    sub.add_parser("devices", help="List available microphone and speaker devices; no recording")
    local = sub.add_parser("local", help="Live microphone → Deepgram STT → fixed TTS → speaker (uses API quota)")
    local.add_argument("--input-device", default=os.getenv("SPARKIE_INPUT_DEVICE"))
    local.add_argument("--output-device", default=os.getenv("SPARKIE_OUTPUT_DEVICE"))
    local.add_argument("--language", help="Override STT language (default: en-US)")
    local.add_argument("--seconds", type=int, default=60, help="Session duration, 1–3600 seconds")
    local.add_argument("--echo-mode", choices=["speaker", "headphones"], default="speaker")
    local.add_argument("--response-mode", choices=["wake", "qa"], default="wake",
                       help="qa enables real contextual answers using the configured reasoning backend")
    local.add_argument("--output", type=Path, default=Path("output/local"))
    zoom = sub.add_parser("zoom", help="Join real Zoom and answer through the meeting SDK virtual microphone")
    zoom.add_argument("--language", default="en-US")
    zoom.add_argument("--seconds", type=int, default=600)
    zoom.add_argument("--response-mode", choices=["realtime", "wake", "qa"], default="realtime",
                      help="realtime: GPT voice + Codex tasks; wake/qa: legacy Deepgram pipeline")
    zoom.add_argument("--output", type=Path, default=Path("output/zoom"))
    workspace = sub.add_parser("workspace", help="Serve meeting workspaces: resolve + snapshot HTTP, WS event bus")
    workspace.add_argument("--host", default="127.0.0.1")
    workspace.add_argument("--port", type=int, default=8790)
    workspace.add_argument("--db", type=Path, default=Path("output/workspace.db"))
    workspace.add_argument("--worker", choices=["codex", "demo"], default="codex",
                           help="demo marks every artifact as simulated; codex runs real background tasks")
    args = parser.parse_args()
    if args.command == "doctor":
        raise SystemExit(doctor())
    if args.command == "devices":
        from .local_session import list_devices
        raise SystemExit(list_devices())
    if args.command == "simulate" and args.interval < 0:
        parser.error("--interval must be non-negative")
    from .local_session import local_session
    if args.command == "zoom":
        if args.response_mode == "realtime":
            from .realtime_session import run as command
            args.transport = "zoom"
        else:
            from .zoom_session import zoom_session as command
    else:
        from .workspace_server import workspace_session
        command = {"simulate": simulate, "tts": tts, "deepgram-check": deepgram_check, "brain-check": brain_check,
                   "local": local_session, "workspace": workspace_session}[args.command]
    if args.command in {"local", "zoom"} and not 1 <= args.seconds <= 3600:
        parser.error("--seconds must be between 1 and 3600")
    try:
        raise SystemExit(asyncio.run(command(args)))
    except (ProviderError, ValueError, TimeoutError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
