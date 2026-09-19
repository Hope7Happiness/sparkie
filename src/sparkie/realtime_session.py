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
from .providers import DeepgramEars, ProviderError
from .realtime import RealtimeAgent
from .realtime_audio import RealtimeLocalAudio
from .task_center import TranscriptLedger, TaskCenter, CodexTaskWorker


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
    def emit(kind, **fields):
        if kind == 'realtime_audio_started' and agent and agent.last_speech_end is not None and audio.audio_origin is not None:
            fields['latency_ms'] = round((fields['dac_time'] - audio.audio_origin) * 1000 - agent.last_speech_end)
            fields['timing_reliable'] = audio.timing_reliable
        event = {'type': kind, 'elapsed_ms': round((time.monotonic() - started) * 1000), **fields}
        if kind in ('assistant_transcript', 'realtime_interrupted'):
            ledger.append({**event, 'source': 'bot', 'note': 'Generated reply text; interruption events mark unplayed content.'})
        line = json.dumps(event, ensure_ascii=False)
        if kind != 'audio_level':
            log.write(line + '\n')
            log.flush()
        print(line, flush=True)
    audio = RealtimeLocalAudio(device_id(args.input_device), device_id(args.output_device),
                              echo_mode=args.echo_mode, max_seconds=args.seconds, on_event=emit)
    center = TaskCenter(ledger, CodexTaskWorker(model=os.getenv('CODEX_MODEL') or 'gpt-5.6-terra'), emit)
    agent = RealtimeAgent(os.environ['OPENAI_API_KEY'], audio, center, emit,
                          model=os.getenv('OPENAI_REALTIME_MODEL') or 'gpt-realtime-2.1')
    dg_ready = asyncio.Event()
    ears = DeepgramEars(os.environ['DEEPGRAM_API_KEY'], session_id, rate=24000,
                        language=args.language, on_ready=dg_ready.set)
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
        try:
            async for record in ears.transcribe(frames(queues[1])):
                ledger.append(record)
                emit('transcript', **asdict(record))
        except Exception as exc:
            dg_active = False
            record = {'type': 'coverage_gap', 'reason': 'deepgram_unavailable',
                      'timestamp_ms': round(audio.captured_samples / 24)}
            ledger.append(record)
            emit('transcript_degraded', error_type=type(exc).__name__, record=record)
            dg_ready.set()
    async def send_audio():
        async for frame in frames(queues[0]):
            await agent.append(frame)
    async def capture():
        nonlocal dg_active
        gated = False
        async for frame in audio.audio():
            current_gate = audio.echo_mode == 'speaker' and time.monotonic() < audio._gate_until
            if current_gate != gated:
                record = {'type': 'coverage_gap' if current_gate else 'coverage_resumed',
                          'timestamp_ms': round(audio.captured_samples / 24), 'reason': 'speaker_echo_gate'}
                ledger.append(record)
                emit('transcript_coverage', **{'record': record})
                gated = current_gate
            for queue in (queues if dg_active else queues[:1]):
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
        for queue in (queues if dg_active else queues[:1]):
            await queue.put(None)
    async def controls():
        reader = asyncio.StreamReader(limit=16384)
        protocol = asyncio.StreamReaderProtocol(reader)
        transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        try:
            while line := await reader.readline():
                try:
                    command = json.loads(line)
                    if command.get('action') == 'interrupt':
                        await agent.interrupt()
                    elif command.get('action') == 'cancel_task':
                        center.cancel(command.get('task_id'))
                    elif command.get('action') == 'report_task':
                        await agent.report_task(command.get('task_id'))
                except (ValueError, TypeError):
                    emit('control_rejected', reason='invalid_command')
        finally:
            transport.close()
    running = []
    reason = 'completed'
    try:
        emit('session_created', session_id=session_id, output=str(directory), model=agent.model)
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
            emit('transcript_ready', provider='deepgram')
        await audio.join()
        emit('listening_ready', language=args.language)
        capturer = asyncio.create_task(capture())
        sender = asyncio.create_task(send_audio())
        control = asyncio.create_task(controls())
        running.extend([capturer, sender, control])
        done, _ = await asyncio.wait([rt, capturer, sender, stopper], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if stopper in done:
            reason = 'stopped'
            audio.request_stop()
        if rt in done:
            raise ProviderError('provider_closed_early')
        # Finish already captured input and flush the final Deepgram utterance.
        await asyncio.wait_for(capturer, 1)
        await asyncio.wait_for(sender, 2)
        try:
            await asyncio.wait_for(asyncio.gather(dg, return_exceptions=True), 2)
        except TimeoutError:
            ledger.append({'type': 'coverage_gap', 'reason': 'deepgram_final_flush_timeout'})
            emit('transcript_degraded', error_type='FinalFlushTimeout')
    except Exception as exc:
        reason = 'failed'
        ledger.append({'type': 'coverage_gap', 'reason': 'session_failed'})
        emit('session_failed', error_type=type(exc).__name__)
    finally:
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        await center.close()
        try:
            await audio.leave()
        except Exception as exc:
            reason = 'failed'
            emit('audio_cleanup_failed', error_type=type(exc).__name__)
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)
        report = {'session_id': session_id, 'exit_reason': reason, 'zoom_tested': False,
                  'model': agent.model, 'audio': audio.diagnostics(), 'transcript_records': len(ledger.records)}
        (directory / 'run.json').write_text(json.dumps(report, indent=2))
        emit('session_stopped', **report)
        log.close()
    return int(reason == 'failed')


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument('--language', choices=['en', 'zh-CN'], default='zh-CN')
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--echo-mode', choices=['speaker', 'headphones'], default='headphones')
    parser.add_argument('--input-device')
    parser.add_argument('--output-device')
    parser.add_argument('--output', type=Path, default=Path('output/realtime'))
    args = parser.parse_args()
    if not 10 <= args.seconds <= 300:
        parser.error('seconds must be 10–300')
    return asyncio.run(run(args))


if __name__ == '__main__':
    raise SystemExit(main())
