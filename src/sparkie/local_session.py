"""Live local microphone session, with persistent event logs for testers."""
import asyncio
import json
import os
import signal
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .engine import Primitive
from .backends import configured_brain
from .local_audio import LocalAudioMeeting
from .providers import DeepgramEars, DeepgramMouth, ProviderError


def device_id(value):
    if value is None or value == "":
        return None
    return int(value) if str(value).isdigit() else value


def list_devices():
    import sounddevice as sd
    print(sd.query_devices())
    print("Use --input-device / --output-device with an index or a unique name.")
    print("Listing devices does not open the microphone or contact Deepgram.")
    return 0


async def local_session(args):
    key = os.getenv("DEEPGRAM_API_KEY")
    if not key:
        raise ValueError("Set DEEPGRAM_API_KEY in .env first")
    response_mode = getattr(args, "response_mode", "wake")
    brain = configured_brain() if response_mode == "qa" else None
    language = args.language or os.getenv("DEEPGRAM_LANGUAGE") or "en"
    session_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    output = args.output / session_id
    output.mkdir(parents=True)
    log_path = output / "events.jsonl"
    with log_path.open("x") as log:
        def event_sink(event):
            line = json.dumps(event, ensure_ascii=False)
            log.write(line + "\n")
            log.flush()
            print(line, flush=True)

        meeting = LocalAudioMeeting(device_id(args.input_device), device_id(args.output_device),
                                    echo_mode=args.echo_mode, max_seconds=args.seconds)
        ears = DeepgramEars(key, session_id, model=os.getenv("DEEPGRAM_MODEL") or "nova-3", language=language)
        mouth = DeepgramMouth(key, os.getenv("DEEPGRAM_TTS_MODEL") or "aura-2-thalia-en")
        engine = Primitive(meeting, ears, mouth, reply=os.getenv("SPARKIE_REPLY") or "I'm here.",
                           brain=brain, mode="local-audio", event_sink=event_sink,
                           question_reply=os.getenv("SPARKIE_QUESTION_REPLY") or "Let me think for a moment.")
        if brain:
            engine.log("reasoning_config", backend=os.getenv("SPARKIE_BACKEND") or "codex",
                       model=brain.model, reasoning_effort=getattr(brain, "reasoning_effort", None))
        meeting.on_event = engine.log
        ears.on_ready = lambda: engine.log("listening_ready", language=language,
                                          hint="Say Sparkie, then pause. Ctrl+C stops the session.")
        loop = asyncio.get_running_loop()
        handlers = {}
        stop_requested = False
        session_task = asyncio.current_task()
        def stop_session():
            nonlocal stop_requested
            if not stop_requested:
                stop_requested = True
                meeting.request_stop()
                session_task.cancel()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                handlers[sig] = signal.getsignal(sig)
                loop.add_signal_handler(sig, stop_session)
            except (NotImplementedError, RuntimeError):
                handlers.pop(sig, None)
        reason = "completed"
        print(f"LIVE microphone → Deepgram → speaker. Language={language}; duration={args.seconds}s; echo={args.echo_mode}.", flush=True)
        print(f"Transcript and event log: {log_path}. No raw microphone audio is saved. Wait for listening_ready.", flush=True)
        try:
            async with asyncio.timeout(args.seconds + 45):
                await engine.run()
        except asyncio.CancelledError:
            reason = "stopped" if stop_requested else "interrupted"
            if not stop_requested:
                raise
            engine.log("session_stopped")
        except Exception as exc:
            reason = "failed"
            engine.log("session_failed", error_type=type(exc).__name__)
            if isinstance(exc, (ValueError, ProviderError)):
                raise
            raise ProviderError("Local audio session failed (" + type(exc).__name__ + "); inspect events.jsonl and check network/audio devices") from None
        finally:
            await meeting.leave()
            for sig, previous in handlers.items():
                loop.remove_signal_handler(sig)
                signal.signal(sig, previous)
            report = engine.report()
            report.update({"session_id": session_id, "exit_reason": reason, "zoom_tested": False,
                           "stt_language": language, "response_mode": response_mode,
                           "brain_backend": (os.getenv("SPARKIE_BACKEND") or "codex") if brain else None,
                           "audio": meeting.diagnostics()})
            (output / "run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(f"Session ended: {output / 'run.json'}", flush=True)
    return 1 if report["response_failures"] else 0
