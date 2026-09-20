"""Parallel local audio → Realtime / Deepgram with a durable Codex task center."""
import argparse
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import sys
import time
from uuid import uuid4

from dotenv import load_dotenv
from .local_session import device_id
from .contracts import SpeechActivity
from .providers import DeepgramEars, ProviderError, failure_details
from .realtime import RealtimeAgent
from .realtime_audio import RealtimeLocalAudio
from .browser_audio import BrowserAudio
from .task_center import TranscriptLedger, TaskCenter
from .task_workers import configured_task_worker
from .event_output import EventOutput
from .semantic_turns import SEMANTIC_EAGERNESS, SemanticTurnEars


async def run(args):
    os.umask(0o077)
    missing = [name for name in ('OPENAI_API_KEY', 'DEEPGRAM_API_KEY') if not os.getenv(name)]
    if missing:
        print(json.dumps({'type': 'configuration_error', 'missing': missing}), flush=True)
        return 1
    session_id = time.strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:8]
    directory = args.output / session_id
    ledger = TranscriptLedger(directory)
    log = (directory / 'events.jsonl').open('a')
    started = time.monotonic()
    agent = None
    transport_name = getattr(args, 'transport', 'local')
    def emit(kind, **fields):
        if kind == 'realtime_audio_started' and agent and agent.last_speech_end is not None and audio.audio_origin is not None:
            fields['latency_ms'] = round((fields['dac_time'] - audio.audio_origin) * 1000 - agent.last_speech_end)
            fields['timing_reliable'] = audio.timing_reliable
        event = {'type': kind, 'elapsed_ms': round((time.monotonic() - started) * 1000), **fields}
        if kind in ('assistant_transcript', 'realtime_interrupted'):
            ledger.append({**event, 'source': 'bot', 'note': 'Generated reply text; interruption events mark unplayed content.'})
            if kind == 'assistant_transcript' and event.get('text'):
                asyncio.get_running_loop().create_task(
                    workspace.utterance(event['text'], 'sparkie', 'bot'))
        elif kind == 'human_turn_committed':
            ledger.append({**event, 'event_id': 'control:' + fields['turn_id']})
            if event.get('text'):
                asyncio.get_running_loop().create_task(
                    workspace.utterance(fields['text'], fields.get('source') or 'human', 'human'))
        elif kind == 'background_task':
            asyncio.get_running_loop().create_task(workspace.task_update(fields))
        line = json.dumps(event, ensure_ascii=False)
        if kind not in ('audio_level', 'audio_output', 'audio_clear', 'transcript_partial'):
            log.write(line + '\n')
            log.flush()
        console.publish(line)
    browser_transport = transport_name == 'browser'
    if transport_name == 'zoom':
        from .realtime_zoom_audio import RealtimeZoomAudio
        from .zoom_audio import ZoomAudioMeeting, ZoomMacAudioMeeting
        from .zoom_config import selected_platform
        from .zoom_macos import paths
        runtime = Path('.runtime/zoom-realtime') / session_id
        if selected_platform() == 'macos':
            meeting = ZoomMacAudioMeeting(runtime, paths(Path(__file__).resolve().parents[2])[2],
                                          max_seconds=args.seconds)
        else:
            meeting = ZoomAudioMeeting(runtime, max_seconds=args.seconds)
        audio = RealtimeZoomAudio(meeting, on_event=emit)
    elif browser_transport:
        audio = BrowserAudio(max_seconds=args.seconds, on_event=emit)
    else:
        audio = RealtimeLocalAudio(device_id(args.input_device), device_id(args.output_device),
                                  echo_mode=args.echo_mode, max_seconds=args.seconds, on_event=emit)
    worker = configured_task_worker()
    center = TaskCenter(ledger, worker, emit)
    output_policy = None
    wake_router = None
    if transport_name == 'zoom':
        from .zoom_output import ZoomOutputPolicy
        # EventOutput is initialized below before any asynchronous session work.
        output_policy = ZoomOutputPolicy(audio, lambda *a, **k: None)
        router_mode = os.getenv('SPARKIE_WAKE_ROUTER') or 'rules'
        if router_mode == 'devin':
            from .wake_router import DevinWakeRouter
            wake_router = DevinWakeRouter(model=os.getenv('SPARKIE_WAKE_MODEL') or 'gemini-3-5-flash-minimal')
        elif router_mode != 'rules':
            raise ValueError('SPARKIE_WAKE_ROUTER must be rules or devin')
    # Mirror the session into a meeting workspace when the server is reachable;
    # every client failure degrades to a no-op so the meeting is unaffected.
    from .workspace_client import WorkspaceClient
    workspace = WorkspaceClient(os.getenv('SPARKIE_WORKSPACE_SERVER') or '127.0.0.1:8790')
    agent = RealtimeAgent(os.environ['OPENAI_API_KEY'], audio, center, emit,
                          model=os.getenv('OPENAI_REALTIME_MODEL') or 'gpt-realtime-2.1',
                          output_policy=output_policy, wake_router=wake_router)
    dg_ready = asyncio.Event()
    ears = DeepgramEars(os.environ['DEEPGRAM_API_KEY'], session_id, rate=24000,
                        model=os.getenv('DEEPGRAM_MODEL') or 'nova-3',
                        language=args.language, on_ready=dg_ready.set,
                        on_partial=lambda text: emit('transcript_partial', text=text))
    participant_stt = getattr(audio, 'participant_transcription', False)
    turn_detection = 'deepgram'
    if participant_stt:
        from .participant_stt import ParticipantEars
        model = os.getenv('DEEPGRAM_MODEL') or 'nova-3'
        turn_detection = os.getenv('SPARKIE_TURN_DETECTION') or 'semantic_vad'
        if turn_detection not in ('semantic_vad', 'deepgram'):
            raise ValueError('SPARKIE_TURN_DETECTION must be semantic_vad or deepgram')
        semantic = turn_detection == 'semantic_vad'
        def participant_ears():
            if semantic:
                return SemanticTurnEars(os.environ['DEEPGRAM_API_KEY'], os.environ['OPENAI_API_KEY'],
                                        session_id, model=agent.model, stt_model=model,
                                        language=args.language, on_event=emit)
            return DeepgramEars(os.environ['DEEPGRAM_API_KEY'], session_id, rate=32000,
                                model=model, language=args.language)
        ears = ParticipantEars(
            participant_ears,
            speaker_name=audio.meeting.speaker_name, is_self=audio.meeting.is_self,
            max_streams=int(os.getenv('SPARKIE_ZOOM_MAX_STT_STREAMS') or '32'), on_event=emit,
            speech_events=True, continuous_silence=semantic, idle_seconds=15 if semantic else 1.5)
        ears.on_ready = dg_ready.set  # Router readiness; connections open when a participant speaks.
    queues = [asyncio.Queue(maxsize=150), asyncio.Queue(maxsize=150)]
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    async def frames(queue):
        while True:
            frame = await queue.get()
            if frame is None:
                return
            yield frame
    dg_active = True
    async def transcribe():
        nonlocal dg_active
        handling_transcript = False
        try:
            source = audio.participant_audio() if participant_stt else frames(queues[1])
            async for record in ears.transcribe(source):
                if isinstance(record, SpeechActivity):
                    handling_transcript = True
                    await agent.participant_speech(record)
                    handling_transcript = False
                    continue
                ledger.append(record)
                emit('transcript', **asdict(record))
                if output_policy is not None:
                    handling_transcript = True
                    await agent.human_transcript(asdict(record))
                    handling_transcript = False
                if record.is_final:
                    await workspace.utterance(record.text, record.speaker, 'human')
        except Exception as exc:
            if handling_transcript:
                stop.set()
                raise  # Agent/native failures are not degraded Deepgram coverage.
            dg_active = False
            if participant_stt:
                try:
                    await agent.participant_input_failed()
                except Exception:
                    stop.set()
                    raise
            record = {'type': 'coverage_gap',
                      'reason': 'semantic_turn_unavailable' if turn_detection == 'semantic_vad' else 'deepgram_unavailable',
                      'timestamp_ms': round(audio.captured_samples / 24)}
            ledger.append(record)
            details = failure_details(exc)
            if details['provider'] == 'unknown':
                details['provider'] = 'semantic_turn' if turn_detection == 'semantic_vad' else 'deepgram'
            emit('transcript_degraded', **details, record=record)
            dg_ready.set()
        finally:
            if participant_stt:
                audio.disable_participant_transcription()
    async def send_audio():
        async for frame in frames(queues[0]):
            await agent.append(frame)
    async def capture():
        nonlocal dg_active
        gated = False
        async for frame in audio.audio():
            current_gate = (frame.gated if frame.gated is not None else
                            audio.echo_mode == 'speaker' and time.monotonic() < audio._gate_until)
            if current_gate != gated:
                record = {'type': 'coverage_gap' if current_gate else 'coverage_resumed',
                          'timestamp_ms': round(audio.captured_samples / 24), 'reason': getattr(audio, 'coverage_reason', 'speaker_echo_gate')}
                if participant_stt:
                    emit('realtime_input_coverage', gated=current_gate, reason='zoom_echo_gate')
                else:
                    ledger.append(record)
                    emit('transcript_coverage', **{'record': record})
                gated = current_gate
            for queue in (queues if dg_active and not participant_stt else queues[:1]):
                try:
                    queue.put_nowait(frame)
                except asyncio.QueueFull:
                    record = {'type': 'coverage_gap', 'reason': 'audio_backpressure'}
                    ledger.append(record)
                    if queue is queues[1]:
                        dg_active = False
                        dg.cancel()
                        emit('transcript_degraded', error_type='AudioBackpressure', record=record)
                    else:
                        raise ProviderError('audio_backpressure') from None
        for queue in (queues if dg_active and not participant_stt else queues[:1]):
            await queue.put(None)
    async def controls():
        reader = asyncio.StreamReader(limit=16384)
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        try:
            while line := await reader.readline():
                try:
                    command = json.loads(line)
                    if not isinstance(command, dict):
                        raise ValueError('invalid control')
                    if browser_transport and command.get('action') in ('audio_input', 'audio_progress', 'audio_settings'):
                        audio.accept(command)
                    elif command.get('action') in ('interrupt', 'human_turn', 'confirm_delivery', 'mute', 'unmute'):
                        await agent.control(command)
                    elif command.get('action') == 'cancel_task':
                        center.cancel(command.get('task_id'))
                    elif command.get('action') == 'report_task':
                        await agent.report_task(command.get('task_id'))
                except (ValueError, TypeError):
                    emit('control_rejected', reason='invalid_command')
                except Exception as exc:
                    emit('audio_failed', reason=type(exc).__name__)
                    stop.set()
                    raise
        finally:
            transport.close()
    running = []
    reason = 'completed'
    failure = None
    # Browser output is a media protocol; CLI output is only a view of events.jsonl.
    console = EventOutput(sys.stdout, required=browser_transport)
    if output_policy is not None:
        output_policy.emit = emit
        emit('zoom_output_state', muted=True, reason='startup', remote_audibility_verified=False)
        emit('zoom_wake_router_config', mode='devin' if wake_router else 'rules',
             model=wake_router.model if wake_router else None,
             timeout_seconds=wake_router.timeout if wake_router else None)
    try:
        external = os.getenv('ZOOM_MEETING_ID') if transport_name == 'zoom' else session_id
        kind = {'zoom': 'zoom_uuid', 'local': 'local_mic'}.get(transport_name, 'browser')
        # A reused meeting number reopens the same workspace; reset gives each
        # join a fresh canvas instead of appending to the previous session.
        if await workspace.open(kind, external or session_id, reset=True,
                                title=f'Zoom {external}' if transport_name == 'zoom' else f'{transport_name} session'):
            # A cancel pressed in the workspace UI lands here as a broadcast.
            workspace.on_message = lambda message: (
                center.cancel(message['task_id'])
                if message.get('type') == 'task.cancelled' and message.get('task_id')
                else None)
            emit('workspace_linked', workspace_id=workspace.workspace_id, external_id=external)
        emit('session_created', session_id=session_id, output=str(directory), model=agent.model, transport=transport_name)
        emit('task_backend_config', backend=worker.backend, model=worker.model)
        center.start()
        emit('transcription_config', provider='deepgram', model=os.getenv('DEEPGRAM_MODEL') or 'nova-3',
             language=args.language, sample_rate=32000 if participant_stt else 24000,
             input_mode='per_participant' if participant_stt else 'mixed',
             foreground_input='participant_final_text' if participant_stt else 'mixed_audio',
             turn_detection=turn_detection, semantic_eagerness=SEMANTIC_EAGERNESS if turn_detection == 'semantic_vad' else None,
             barge_in='participant_interim_text' if participant_stt else 'mixed_input')
        rt = asyncio.create_task(agent.run())
        dg = asyncio.create_task(transcribe())
        running.extend([rt, dg])
        async def wait_ready():
            await asyncio.gather(agent.ready.wait(), dg_ready.wait())
        readiness = asyncio.create_task(wait_ready())
        stopper = asyncio.create_task(stop.wait())
        running.extend([readiness, stopper])
        done, _ = await asyncio.wait([rt, readiness, stopper], timeout=25, return_when=asyncio.FIRST_COMPLETED)
        if stopper in done:
            reason = 'stopped'
            return 0
        for task in (rt,):
            if task in done:
                task.result()
                raise ProviderError('provider_closed_before_ready')
        if readiness not in done:
            raise ProviderError('provider_startup_timeout')
        if dg_active:
            emit('transcript_ready', provider='deepgram',
                 readiness='router' if participant_stt else 'provider_connection')
        joining = asyncio.create_task(audio.join())
        running.append(joining)
        done, _ = await asyncio.wait([joining, rt, stopper], return_when=asyncio.FIRST_COMPLETED)
        if stopper in done:
            reason = 'stopped'
            return 0
        if rt in done:
            rt.result()
            raise ProviderError('provider_closed_during_audio_join')
        joining.result()
        emit('listening_ready', language=args.language, transport=transport_name,
             configured_duration_seconds=args.seconds,
             duration_basis='from_listening_ready' if args.seconds else 'manual_stop',
             duration_deadline_elapsed_ms=(round((time.monotonic() - started + args.seconds) * 1000)
                                           if args.seconds else None))
        # Share the workspace present view as the agent's screen once the bridge
        # is connected; share failures degrade to events, never session failures.
        meeting_obj = getattr(audio, 'meeting', None)
        if transport_name == 'zoom' and workspace.workspace_id and \
                hasattr(meeting_obj, 'share_screen'):
            try:
                scheme = 'http' if '://' not in workspace.server else ''
                base = workspace.server if not scheme else f'{scheme}://{workspace.server}'
                await meeting_obj.share_screen(
                    f'{base}/workspaces/{workspace.workspace_id}/present')
                emit('zoom_share_requested', workspace_id=workspace.workspace_id)
            except Exception as exc:
                emit('zoom_share_failed', error_type=type(exc).__name__)
        capturer = asyncio.create_task(capture())
        sender = asyncio.create_task(send_audio())
        control = asyncio.create_task(controls())
        notifier = asyncio.create_task(agent.notify_tasks())
        running.extend([capturer, sender, control, notifier])
        done, _ = await asyncio.wait([rt, capturer, sender, stopper, notifier], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if dg.done():
            dg.result()
        if stopper in done:
            reason = 'stopped'
            audio.request_stop()
        if rt in done:
            raise ProviderError('provider_closed_early')
        # Finish already captured input and flush the final Deepgram utterance.
        await asyncio.wait_for(capturer, 1)
        await asyncio.wait_for(sender, 2)
        if reason != 'stopped' and getattr(audio, 'duration_expired', False):
            reason = 'duration_elapsed'
            emit('session_duration_elapsed', configured_duration_seconds=args.seconds,
                 message='Configured session duration reached; ending the session cleanly.')
        if reason == 'completed' and getattr(audio, 'meeting_ended', False):
            reason = 'meeting_ended'
        try:
            await asyncio.wait_for(asyncio.gather(dg, return_exceptions=True), 10 if participant_stt else 2)
        except TimeoutError:
            ledger.append({'type': 'coverage_gap', 'reason': 'deepgram_final_flush_timeout'})
            emit('transcript_degraded', error_type='FinalFlushTimeout')
    except Exception as exc:
        reason = 'failed'
        failure = failure_details(exc)
        ledger.append({'type': 'coverage_gap', 'reason': 'session_failed'})
        emit('session_failed', **failure)
    finally:
        for task in running:
            task.cancel()
        # Persist task cancellation before waiting for provider socket cleanup.
        # The web supervisor may terminate an unresponsive process after ten seconds.
        await center.close()
        await asyncio.gather(*running, return_exceptions=True)
        try:
            await audio.leave()
        except Exception as exc:
            reason = 'failed'
            emit('audio_cleanup_failed', error_type=type(exc).__name__)
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)
        report = {'session_id': session_id, 'exit_reason': reason, 'transport': transport_name,
                  'configured_duration_seconds': args.seconds,
                  'remote_audibility_verified': False,
                  'model': agent.model, 'audio': audio.diagnostics(), 'transcript_records': len(ledger.records),
                  'transcript': sorted((r for r in ledger.records if r.get('speaker_id')),
                                       key=lambda r: (r.get('timestamp_ms', 0), r.get('event_id', '')))}
        if failure is not None:
            report['failure'] = failure
        try:
            emit('session_stopped', **report)
            await workspace.end_meeting()
        finally:
            await workspace.close()
            await console.close()
            report['event_output'] = console.diagnostics()
            if console.required and (console.failure or console.dropped):
                reason = report['exit_reason'] = 'failed'
            (directory / 'run.json').write_text(json.dumps(report, indent=2))
            log.close()
    return int(reason == 'failed')


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument('--transport', choices=['local', 'browser', 'zoom'], default='local')
    parser.add_argument('--language', choices=['en-US', 'en', 'zh-CN'], default='en-US')
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--echo-mode', choices=['speaker', 'headphones'], default='speaker')
    parser.add_argument('--input-device')
    parser.add_argument('--output-device')
    parser.add_argument('--output', type=Path, default=Path('output/realtime'))
    args = parser.parse_args()
    if not (1 <= args.seconds <= 3600 or (args.transport == 'browser' and args.seconds == 0)):
        parser.error('seconds must be 1–3600, or 0 for a browser session ended manually')
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
