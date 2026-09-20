"""Durable transcript and bounded, asynchronous background jobs."""
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import time
from uuid import uuid4

from .task_workers import CodexTaskWorker, DevinTaskWorker, configured_task_worker
from .local_actions import run_local_action


class TranscriptLedger:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.records = []
        self.seen = set()

    def append(self, record):
        record = asdict(record) if not isinstance(record, dict) else dict(record)
        identifier = record.get('event_id')
        if identifier and identifier in self.seen:
            return
        if identifier:
            self.seen.add(identifier)
        with (self.directory / 'transcript.jsonl').open('a') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        self.records.append(record)

    def snapshot(self):
        # JSON round trip: each task owns an immutable, complete snapshot.
        return json.loads(json.dumps(self.records))


class TaskCenter:
    def __init__(self, ledger, worker, emit):
        self.ledger, self.worker, self.emit = ledger, worker, emit
        self.jobs, self.runners = {}, {}
        self.semaphore = asyncio.Semaphore(1)
        self.notifications = asyncio.Queue()
        self.notified = set()
        self.updates = {}
        self.warmup = None

    def start(self):
        if hasattr(self.worker, 'start') and self.warmup is None:
            async def prepare():
                self.emit('task_backend_starting', backend=self.worker.backend)
                try:
                    await self.worker.start()
                    self.emit('task_backend_ready', backend=self.worker.backend, model=self.worker.model,
                              agent_session_id=self.worker.session_id)
                except Exception as exc:
                    self.emit('task_backend_failed', backend=self.worker.backend, error_type=type(exc).__name__)
            self.warmup = asyncio.create_task(prepare())

    def _save(self, job):
        path = self.ledger.directory / 'tasks.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(list(self.jobs.values()), ensure_ascii=False, indent=2))
        temporary.replace(path)
        self.emit('background_task', **{k: v for k, v in job.items() if k != 'snapshot'})
        if job['status'] in ('completed', 'failed') and job['task_id'] not in self.notified:
            self.notified.add(job['task_id'])
            self.notifications.put_nowait(self.status(job['task_id']))

    def submit(self, request, *, action=None, arguments=None):
        if not isinstance(request, str) or not request.strip() or len(request) > 8000:
            return {'error': 'invalid_request'}
        task_id = uuid4().hex[:12]
        snapshot = self.ledger.snapshot()
        job = {'task_id': task_id, 'request': request, 'status': 'queued', 'created_at': time.time(),
               'transcript_records': len(snapshot), 'snapshot': snapshot,
               'context_note': 'All finalized transcript available at delegation; newer speech is not included. '
                               'The request also carries speech heard directly by Realtime.'}
        if action is not None:
            if action not in ('create_desktop_file', 'open_website') or not isinstance(arguments, dict):
                return {'error': 'invalid_local_action'}
            job.update(action=action, arguments=dict(arguments))
        self.jobs[task_id] = job
        self.updates[task_id] = asyncio.Queue()
        self._save(job)
        self.runners[task_id] = asyncio.create_task(self._run(job))
        return {'task_id': task_id, 'status': 'queued', 'awaiting_background': True,
                'transcript_records': len(snapshot), 'context_note': job['context_note']}

    async def _run(self, job):
        try:
            if job.get('action'):
                job.update(status='running', started_at=time.time(), progress='正在执行本机操作')
                self._save(job)
                job['result'] = await run_local_action(job['action'], job['arguments'])
                job['status'] = 'completed'
            else:
                await self._run_worker(job)
        except asyncio.CancelledError:
            job['status'] = 'cancelled'
        except Exception as exc:
            job.update(status='failed', error_type=type(exc).__name__)
            if isinstance(exc, FileExistsError):
                job['error_message'] = '同名文件已存在，未覆盖。请指定另一个文件名。'
            elif job.get('action') == 'open_website':
                if isinstance(exc, FileNotFoundError):
                    job['error_message'] = '本地 HTML 文件不存在或不是普通文件，请确认文件路径。'
                elif isinstance(exc, ValueError):
                    job['error_message'] = '仅支持 HTTP/HTTPS 网址或本机已存在的 HTML 文件地址（file:///…html）。'
        finally:
            job['finished_at'] = time.time()
            self._save(job)

    async def _run_worker(self, job):
        async with self.semaphore:
            job.update(status='running', started_at=time.time(),
                       backend=getattr(self.worker, 'backend', 'unknown'), model=getattr(self.worker, 'model', None))
            self._save(job)
            def progress(**fields):
                job.update(**fields, progress_at=time.time())
                self._save(job)
            if getattr(self.worker, 'supports_updates', False):
                job['result'] = await self.worker.run_with_progress(
                    job['request'], job['snapshot'], progress, updates=self.updates[job['task_id']],
                    initial_revision=job.get('revision', 0))
            elif hasattr(self.worker, 'run_with_progress'):
                job['result'] = await self.worker.run_with_progress(job['request'], job['snapshot'], progress)
            else:
                job['result'] = await self.worker.run(job['request'], job['snapshot'])
            job['status'] = 'completed'

    def status(self, task_id):
        job = self.jobs.get(task_id)
        return {k: v for k, v in job.items() if k != 'snapshot'} if job else {'error': 'unknown_task'}

    def update(self, task_id, request):
        job = self.jobs.get(task_id)
        if not job:
            return {'error': 'unknown_task'}
        running_update = (job['status'] == 'running' and not job.get('action')
                          and getattr(self.worker, 'supports_updates', False))
        if job['status'] != 'queued' and not running_update:
            return {'error': 'task_already_started', 'status': job['status'],
                    'note': 'This request was not changed. Do not claim the running action was redirected.'}
        if job.get('action'):
            return {'error': 'local_action_not_editable',
                    'note': 'The action was not changed. Check its result before requesting a new action.'}
        if not isinstance(request, str) or not request.strip() or len(request) > 8000:
            return {'error': 'invalid_request'}
        job.setdefault('request_history', []).append({'request': job['request'],
                                                     'revision': job.get('revision', 0)})
        job.update(request=request, snapshot=self.ledger.snapshot(),
                   transcript_records=len(self.ledger.records), updated_at=time.time(),
                   revision=job.get('revision', 0) + 1)
        if running_update:
            self.updates[task_id].put_nowait((request, job['snapshot'], job['revision']))
            job.update(update_delivery='pending',
                       progress='修改已排队，等待后台接收；已执行的操作不会撤销')
        self._save(job)
        return self.status(task_id)

    def cancel(self, task_id):
        runner = self.runners.get(task_id)
        if runner and not runner.done():
            runner.cancel()
            job = self.jobs[task_id]
            job.update(status='cancelled', finished_at=time.time())
            self._save(job)
        return self.status(task_id)

    async def close(self):
        if self.warmup:
            self.warmup.cancel()
        for runner in self.runners.values():
            runner.cancel()
        # The whole voice session is ending: close the persistent process now,
        # rather than waiting for a turn cancellation to consume the web shutdown grace period.
        if hasattr(self.worker, 'close'):
            await self.worker.close()
        await asyncio.gather(*self.runners.values(), return_exceptions=True)
        if self.warmup:
            await asyncio.gather(self.warmup, return_exceptions=True)
        # A runner cancelled before its first scheduling never enters its finally block.
        for job in self.jobs.values():
            if job['status'] in ('queued', 'running'):
                job.update(status='cancelled', finished_at=time.time())
                self._save(job)
