import asyncio
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest

from sparkie.agent_runtime import AgentRuntime
from sparkie.event_bus import EventBus
from sparkie.task_artifacts import materialize_result, MAX_DOCUMENT_BYTES, MAX_IMAGE_BYTES
from sparkie.task_center import TaskCenter, TranscriptLedger
from sparkie.workspace import WorkspaceStore


def completion(path):
    return 'Created the Markdown report.\n\n```sparkie-artifact\n' + json.dumps({'path': str(path)}) + '\n```'


class DocumentTests(unittest.TestCase):
    def test_image_snapshot_uses_browser_media_not_markdown_wrapper(self):
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8ZkAAAAASUVORK5CYII=')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'chart.png'
            path.write_bytes(png)
            output = materialize_result(completion(path), directory)
            path.unlink()
            self.assertEqual(output['artifact']['type'], 'image')
            content = output['artifact']['content']
            self.assertNotIn('markdown', content)
            self.assertTrue(content['image'].startswith('data:image/png;base64,'))
            self.assertEqual(base64.b64decode(content['image'].split(',')[1]), png)
            self.assertEqual(content['filename'], 'chart.png')
            for data in (b'<html>not an image</html>', png + b'x' * MAX_IMAGE_BYTES):
                path.write_bytes(data)
                self.assertIn('artifact_error', materialize_result(completion(path), directory))
            svg = Path(directory) / 'chart.svg'
            svg.write_text('<svg/>')
            self.assertEqual(materialize_result(completion(svg), directory)['artifact_error'],
                             'unsupported_document_type')

    def test_explicit_document_is_snapshotted_and_plain_paths_are_not_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'report with spaces.md'
            body = '# Actual report\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n'
            path.write_text(body)
            output = materialize_result(completion(path), directory)
            path.unlink()
            self.assertEqual(output['artifact']['content']['markdown'], body)
            self.assertEqual(output['result'], 'Created the Markdown report.')
            prose = 'Discuss the reference file: ' + str(path)
            self.assertEqual(materialize_result(prose, directory), {'result': prose})

    def test_missing_unsupported_oversized_empty_and_invalid_documents_are_not_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = [('missing.md', None), ('report.html', b'html'),
                     ('large.md', b'a' * (MAX_DOCUMENT_BYTES + 1)),
                     ('empty.md', b''), ('binary.md', b'\xff')]
            for name, data in cases:
                with self.subTest(name=name):
                    path = root / name
                    if data is not None:
                        path.write_bytes(data)
                    output = materialize_result(completion(path), directory)
                    self.assertIn('artifact_error', output)
                    self.assertNotIn('artifact', output)
            fifo = root / 'pipe.md'
            os.mkfifo(fifo)
            self.assertEqual(materialize_result(completion(fifo), root)['artifact_error'],
                             'document_not_regular_file')
            self.assertIn('artifact_error', materialize_result(completion(root) + '\n' + completion(root), root))
            self.assertIn('artifact_error', materialize_result('```sparkie-artifact\n{}\n```', root))

    def test_traversal_and_symlinks_cannot_escape_output_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'workspace'
            root.mkdir()
            outside = root.parent / 'private.md'
            outside.write_text('private')
            link = root / 'link.md'
            link.symlink_to(outside)
            for path in (outside, link, '../private.md'):
                self.assertEqual(materialize_result(completion(path), root)['artifact_error'],
                                 'document_outside_output_roots')


class DocumentPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_realtime_names_output_before_worker_runs_and_title_survives_completion(self):
        from unittest.mock import AsyncMock
        from sparkie.realtime import RealtimeAgent
        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory) / 'board.db')
            runtime = AgentRuntime(store, EventBus())
            ws = store.create_workspace('fixture', 'named')
            release = asyncio.Event()
            class Worker:
                async def run(self, *args):
                    await release.wait()
                    return '# Actual report heading\n\nActual contents'
            center = TaskCenter(TranscriptLedger(Path(directory) / 'ledger'), Worker(),
                                lambda kind, **fields: runtime.mirror_task(ws, fields))
            agent = RealtimeAgent('fixture', None, center, lambda *a, **k: None)
            agent.send = AsyncMock()
            try:
                await agent.handle({'type': 'response.function_call_arguments.done', 'response_id': 'fixture',
                    'call_id': 'name', 'name': 'delegate_task', 'arguments': json.dumps({
                        'request': 'Research lots of execution details not suitable for display',
                        'artifact_title': 'Boston weather report'})})
                job = next(iter(center.jobs.values()))
                self.assertEqual(store.snapshot(ws)['tasks'][0]['artifact_title'], 'Boston weather report')
                self.assertEqual(job['status'], 'queued')
                release.set()
                await center.runners[job['task_id']]
                self.assertEqual(store.snapshot(ws)['artifacts'][0]['title'], 'Boston weather report')
                self.assertEqual(center.status(job['task_id'])['artifact_title'], 'Boston weather report')
                self.assertEqual(center.submit('test', artifact_title='x' * 81)['error'], 'invalid_artifact_title')
            finally:
                await center.close()
                store.close()

    async def test_worker_file_reaches_board_without_changing_presentation_or_voice_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory) / 'board.db')
            bus = EventBus()
            runtime = AgentRuntime(store, bus)
            workspace = store.create_workspace('fixture', 'document')
            old = store.create_artifact(workspace, title='Selected document')
            store.set_active_artifact(workspace, old)
            body = '# Actual deliverable\n\nThis is the document itself.\n'
            class Worker:
                workspace = Path(directory)
                async def run(self, request, transcript):
                    path = self.workspace / 'report.md'
                    path.write_text(body)
                    return completion(path)
            center = TaskCenter(TranscriptLedger(Path(directory) / 'ledger'), Worker(),
                                lambda kind, **fields: runtime.mirror_task(workspace, fields))
            try:
                task_id = center.submit('Write a report')['task_id']
                await center.runners[task_id]
                snapshot = store.snapshot(workspace)
                artifact = snapshot['artifacts'][-1]
                self.assertEqual(artifact['content']['markdown'], body)
                self.assertEqual(artifact['title'], 'Actual deliverable')
                self.assertEqual(snapshot['tasks'][0]['result'], 'Created the Markdown report.')
                self.assertEqual(snapshot['state']['active_artifact_id'], old)
                notice = center.notifications.get_nowait()
                self.assertNotIn('content', notice['artifact'])
                self.assertEqual(notice['result'], 'Created the Markdown report.')
                center._save(center.jobs[task_id])
                self.assertEqual(len(store.snapshot(workspace)['artifacts']), 2)
                self.assertTrue(runtime.artifact_control(workspace, 'present', artifact['artifact_id'])['ok'])
            finally:
                await center.close()
                store.close()

    async def test_unreadable_deliverable_does_not_become_summary_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory) / 'board.db')
            runtime = AgentRuntime(store, EventBus())
            workspace = store.create_workspace('fixture', 'missing')
            class Worker:
                workspace = Path(directory)
                async def run(self, *args):
                    return completion(self.workspace / 'missing.md')
            center = TaskCenter(TranscriptLedger(Path(directory) / 'ledger'), Worker(),
                                lambda kind, **fields: runtime.mirror_task(workspace, fields))
            try:
                task_id = center.submit('Write a report')['task_id']
                await center.runners[task_id]
                self.assertEqual(store.snapshot(workspace)['artifacts'], [])
                self.assertIn('artifact_error', center.status(task_id))
                self.assertIn('Document preview unavailable', store.snapshot(workspace)['tasks'][0]['error'])
            finally:
                await center.close()
                store.close()
