"""Run the existing voice engine inside a real Zoom meeting."""
import asyncio
import json
import os
import signal
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path
from .backends import configured_brain
from .engine import Primitive
from .providers import DeepgramEars, DeepgramMouth, ProviderError
from .zoom_audio import ZoomAudioMeeting, ZoomMacAudioMeeting
from .zoom_config import selected_platform


async def zoom_session(args):
    key = os.getenv('DEEPGRAM_API_KEY')
    if not key:
        raise ValueError('Set DEEPGRAM_API_KEY first')
    session_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:6]
    output = args.output / session_id
    output.mkdir(parents=True)
    runtime = Path('.runtime/zoom-voice') / session_id
    if selected_platform() == 'macos':
        from .zoom_macos import paths
        meeting = ZoomMacAudioMeeting(runtime, paths(Path(__file__).resolve().parents[2])[2],
                                      max_seconds=args.seconds)
    else:
        meeting = ZoomAudioMeeting(runtime, max_seconds=args.seconds)
    brain = configured_brain() if args.response_mode == 'qa' else None
    ears = DeepgramEars(key, session_id, language=args.language,
                        model=os.getenv('DEEPGRAM_MODEL') or 'nova-3')
    mouth = DeepgramMouth(key, os.getenv('DEEPGRAM_TTS_MODEL') or 'aura-2-thalia-en')
    with (output / 'events.jsonl').open('x') as log:
        def sink(event):
            line = json.dumps(event, ensure_ascii=False)
            log.write(line+'\n'); log.flush()
            print(line, flush=True)
        engine = Primitive(meeting, ears, mouth, reply=os.getenv('SPARKIE_REPLY') or "I'm here.",
                           brain=brain, mode='zoom-audio', event_sink=sink,
                           question_reply=os.getenv('SPARKIE_QUESTION_REPLY') or 'Let me think for a moment.')
        meeting.on_event = engine.log
        ears.on_ready = lambda: engine.log('listening_ready', language=args.language, platform='zoom')
        if brain:
            engine.log('reasoning_config', model=brain.model, reasoning_effort=getattr(brain, 'reasoning_effort', None))
        task = asyncio.current_task()
        stopped = False
        def stop():
            nonlocal stopped
            stopped = True
            task.cancel()
        loop = asyncio.get_running_loop()
        handlers = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            handlers[sig] = signal.getsignal(sig)
            loop.add_signal_handler(sig, stop)
        reason = 'completed'
        try:
            async with asyncio.timeout(args.seconds + 165):
                await engine.run()
        except asyncio.CancelledError:
            reason = 'stopped'
            if not stopped:
                raise
        except Exception as exc:
            reason = 'failed'
            engine.log('session_failed', error_type=type(exc).__name__)
            raise ProviderError('Zoom voice session failed (' + type(exc).__name__ + '); inspect events.jsonl and host admission/audio permissions') from None
        finally:
            try:
                await meeting.leave()
            except Exception as cleanup_error:
                reason = 'failed'
                engine.log('zoom_cleanup_failed', container=meeting.name, error_type=type(cleanup_error).__name__)
            for sig, previous in handlers.items():
                loop.remove_signal_handler(sig)
                signal.signal(sig, previous)
            report = engine.report()
            report.update(session_id=session_id, exit_reason=reason, audio=meeting.diagnostics())
            (output / 'run.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            print(f'Session report: {output / "run.json"}', flush=True)
    return 1 if report['response_failures'] or reason == 'failed' else 0
