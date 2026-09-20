"""Durable transcript and bounded, asynchronous background jobs."""
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import time
from uuid import uuid4

from .task_workers import CodexTaskWorker, DevinTaskWorker, configured_task_worker
from .task_artifacts import materialize_result


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
        if job['status'] in ('completed', 'failed') and 'announcement' not in job:
            job['announcement'] = {'state': 'pending', 'attempt': 0,
                                   'order': len(self.notified)}
        path = self.ledger.directory / 'tasks.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(list(self.jobs.values()), ensure_ascii=False, indent=2))
        temporary.replace(path)
        self.emit('background_task', **{k: v for k, v in job.items() if k != 'snapshot'})
        if job['status'] in ('completed', 'failed') and job['task_id'] not in self.notified:
            self.notified.add(job['task_id'])
            self.notifications.put_nowait(self.status(job['task_id']))

    def pending_announcements(self):
        return [self.status(job['task_id']) for job in sorted(
            (j for j in self.jobs.values() if j.get('announcement', {}).get('state') == 'pending'),
            key=lambda j: j['announcement']['order'])]

    def mark_output_origin(self, task_id):
        self.jobs[task_id]['zoom_output_origin'] = 'addressed_turn'
        self._save(self.jobs[task_id])

    def offer_announcements(self, task_ids):
        offers = []
        for task_id in task_ids:
            job = self.jobs[task_id]
            notice = job['announcement']
            if notice['state'] != 'pending':
                continue
            notice.update(state='offered', attempt=notice['attempt'] + 1)
            self._save(job)
            offers.append({'task_id': task_id, 'attempt': notice['attempt']})
        return offers

    def defer_announcements(self, offers):
        # Offered means context supplied, never that a listener heard the result.
        for offer in offers:
            job = self.jobs.get(offer['task_id'], {})
            notice = job.get('announcement', {})
            if notice.get('state') == 'offered' and notice['attempt'] == offer['attempt']:
                notice['state'] = 'pending'
                self._save(job)

    def confirm_announcement(self, task_id, attempt):
        job = self.jobs.get(task_id)
        notice = job.get('announcement', {}) if job else {}
        if (type(attempt) is not int or notice.get('attempt') != attempt or
                notice.get('state') not in ('offered', 'confirmed')):
            return False
        if notice['state'] != 'confirmed':
            notice['state'] = 'confirmed'
            self._save(job)
            self.emit('background_notification_confirmed', task_id=task_id, attempt=attempt,
                      basis='explicit_human_confirmation')
        return True

    def submit(self, request, artifact_title=None):
        if not isinstance(request, str) or not request.strip() or len(request) > 8000:
            return {'error': 'invalid_request'}
        if artifact_title is not None:
            if not isinstance(artifact_title, str) or not artifact_title.strip() or len(artifact_title) > 80:
                return {'error': 'invalid_artifact_title'}
            artifact_title = ' '.join(artifact_title.split())
        task_id = uuid4().hex[:12]
        snapshot = self.ledger.snapshot()
        job = {'task_id': task_id, 'request': request, 'artifact_title': artifact_title,
               'status': 'queued', 'created_at': time.time(),
               'transcript_records': len(snapshot), 'snapshot': snapshot,
               'context_note': 'All finalized transcript available at delegation; newer speech is not included. '
                               'The request also carries speech heard directly by Realtime.'}
        self.jobs[task_id] = job
        self.updates[task_id] = asyncio.Queue()
        self._save(job)
        self.runners[task_id] = asyncio.create_task(self._run(job))
        return {'task_id': task_id, 'status': 'queued', 'awaiting_background': True,
                'artifact_title': artifact_title,
                'transcript_records': len(snapshot), 'context_note': job['context_note']}

    async def _run(self, job):
        try:
            await self._run_worker(job)
        except asyncio.CancelledError:
            job['status'] = 'cancelled'
        except Exception as exc:
            job.update(status='failed', error_type=type(exc).__name__)
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
            job.update(await asyncio.to_thread(materialize_result, job['result'],
                                               getattr(self.worker, 'workspace', Path.cwd())))
            job['status'] = 'completed'

    def status(self, task_id):
        job = self.jobs.get(task_id)
        if not job:
            return {'error': 'unknown_task'}
        status = {k: v for k, v in job.items() if k not in ('snapshot', 'artifact')}
        if job.get('artifact'):
            status['artifact'] = {'source_path': job['artifact']['source_path']}
        return json.loads(json.dumps(status))

    def update(self, task_id, request):
        job = self.jobs.get(task_id)
        if not job:
            return {'error': 'unknown_task'}
        running_update = (job['status'] == 'running'
                          and getattr(self.worker, 'supports_updates', False))
        if job['status'] != 'queued' and not running_update:
            return {'error': 'task_already_started', 'status': job['status'],
                    'note': 'This request was not changed. Do not claim the running action was redirected.'}
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
                       progress='Update queued for the worker; completed actions are not rolled back')
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
