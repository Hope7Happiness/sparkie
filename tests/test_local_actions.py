import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

from sparkie.local_actions import run_local_action
from sparkie.task_center import TranscriptLedger, TaskCenter

class LocalActionTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_is_verified_exclusive_and_stays_on_desktop(self):
        with tempfile.TemporaryDirectory() as directory, patch('sparkie.local_actions.Path.home', return_value=Path(directory)):
            desktop = Path(directory) / 'Desktop'; desktop.mkdir()
            result = await run_local_action('create_desktop_file', {'filename': 'test.txt', 'content': 'hello'})
            self.assertIn('verified', result)
            self.assertEqual((desktop / 'test.txt').read_text(), 'hello')
            with self.assertRaises(FileExistsError):
                await run_local_action('create_desktop_file', {'filename': 'test.txt', 'content': 'overwrite'})
            self.assertEqual((desktop / 'test.txt').read_text(), 'hello')
            with self.assertRaises(ValueError):
                await run_local_action('create_desktop_file', {'filename': '../escape.txt', 'content': 'bad'})

    async def test_fast_action_does_not_wait_for_codex_queue(self):
        class Worker:
            async def run(self, *args): await asyncio.Event().wait()
        with tempfile.TemporaryDirectory() as directory, patch('sparkie.local_actions.Path.home', return_value=Path(directory)):
            (Path(directory) / 'Desktop').mkdir()
            center = TaskCenter(TranscriptLedger(Path(directory) / 'session'), Worker(), lambda *a, **kw: None)
            slow = center.submit('long research')['task_id']
            await asyncio.sleep(0)
            fast = center.submit('create file', action='create_desktop_file',
                                 arguments={'filename': 'quick.txt', 'content': 'ready'})['task_id']
            await asyncio.wait_for(center.runners[fast], 5)
            self.assertEqual(center.status(fast)['status'], 'completed')
            self.assertEqual(center.status(slow)['status'], 'running')
            await center.close()

    async def test_browser_url_is_argument_and_does_not_claim_page_loaded(self):
        process = AsyncMock(); process.wait.return_value = 0
        with patch('sparkie.local_actions.shutil.which', return_value='/usr/bin/open'), \
             patch('sparkie.local_actions.asyncio.create_subprocess_exec', return_value=process) as launch:
            result = await run_local_action('open_website', {'url': 'https://example.com/path?a=1&b=2'})
            self.assertIn('not independently verified', result)
            self.assertEqual(launch.call_args.args, ('/usr/bin/open', 'https://example.com/path?a=1&b=2'))
            with self.assertRaises(ValueError):
                await run_local_action('open_website', {'url': 'file:///etc/passwd'})

    async def test_local_html_with_spaces_opens_and_invalid_targets_never_launch(self):
        process = AsyncMock(); process.wait.return_value = 0
        with tempfile.TemporaryDirectory() as directory, \
             patch('sparkie.local_actions.shutil.which', return_value='/usr/bin/open'), \
             patch('sparkie.local_actions.asyncio.create_subprocess_exec', return_value=process) as launch:
            report = Path(directory) / 'research report.html'
            report.write_text('<html><title>Report</title></html>')
            url = report.as_uri() + '#results'
            result = await run_local_action('open_website', {'url': url})
            self.assertIn('not independently verified', result)
            self.assertEqual(launch.call_args.args, ('/usr/bin/open', report.resolve().as_uri() + '#results'))
            launch.reset_mock()
            for invalid in ('file://remotehost/report.html', 'file:relative.html',
                            'file:///tmp/report%00.html', 'file:///tmp/script.sh',
                            'javascript:alert(1)', 'file:///tmp/a\n.html'):
                with self.subTest(url=invalid), self.assertRaises(ValueError):
                    await run_local_action('open_website', {'url': invalid})
            with self.assertRaises(FileNotFoundError):
                await run_local_action('open_website', {'url': (Path(directory) / 'missing.html').as_uri()})
            launch.assert_not_called()

    async def test_open_failure_explains_missing_file_in_task_result(self):
        with tempfile.TemporaryDirectory() as directory:
            center = TaskCenter(TranscriptLedger(Path(directory) / 'session'), object(), lambda *a, **kw: None)
            task = center.submit('open report', action='open_website',
                                 arguments={'url': (Path(directory) / 'missing.html').as_uri()})['task_id']
            await center.runners[task]
            self.assertEqual(center.status(task)['status'], 'failed')
            self.assertIn('本地 HTML 文件不存在', center.status(task)['error_message'])
            await center.close()
