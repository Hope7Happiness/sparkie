import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest

from sparkie.agent_runtime import AgentRuntime
from sparkie.event_bus import EventBus
from sparkie.task_artifacts import materialize_result, MAX_DOCUMENT_BYTES
from sparkie.task_center import TaskCenter, TranscriptLedger
from sparkie.workspace import WorkspaceStore


def completion(path):
    return 'Created the Markdown report.\n\n```sparkie-artifact\n' + json.dumps({'path': str(path)}) + '\n```'


class DocumentTests(unittest.TestCase):
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
