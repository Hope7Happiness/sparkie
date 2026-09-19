import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from sparkie.backends import CodexBrain, configured_brain
from sparkie.providers import ProviderError


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_codex_uses_stdin_saved_login_and_readonly_workspace(self):
        captured = {}
        class Process:
            returncode = 0
            async def communicate(self, data):
                captured['prompt'] = data.decode()
                return b'', b''
        async def spawn(*args, **kwargs):
            captured['args'], captured['kwargs'] = args, kwargs
            Path(args[args.index('--output-last-message') + 1]).write_text('Zoom and Deepgram.')
            return Process()
        with patch.dict(os.environ, {'DEEPGRAM_API_KEY':'secret', 'OPENAI_API_KEY':'secret', 'CODEX_API_KEY':'secret'}), \
             patch('sparkie.backends.shutil.which', return_value='/bin/codex'), \
             patch('sparkie.backends.asyncio.create_subprocess_exec', side_effect=spawn):
            answer = await CodexBrain().answer(['We chose Zoom.', 'Sparkie, summarize.'])
        self.assertEqual(answer, 'Zoom and Deepgram.')
        self.assertEqual(captured['args'][-1], '-')
        self.assertIn('read-only', captured['args'])
        self.assertIn('features.shell_tool=false', captured['args'])
        self.assertIn('We chose Zoom.', captured['prompt'])
        for key in ['DEEPGRAM_API_KEY','OPENAI_API_KEY','CODEX_API_KEY']:
            self.assertNotIn(key, captured['kwargs']['env'])

    async def test_codex_timeout_terminates_worker(self):
        class Process:
            returncode = None
            pid = 12345
            waited = False
            async def communicate(self, data):
                await asyncio.sleep(10)
            async def wait(self):
                self.waited = True
        process = Process()
        async def spawn(*args, **kwargs):
            return process
        with patch('sparkie.backends.shutil.which', return_value='/bin/codex'), \
             patch('sparkie.backends.asyncio.create_subprocess_exec', side_effect=spawn), \
             patch('sparkie.backends.os.killpg') as kill:
            with self.assertRaisesRegex(ProviderError, 'timed out'):
                await CodexBrain(timeout=.01).answer(['test'])
            kill.assert_called_once()
            self.assertTrue(process.waited)

    async def test_missing_codex_fails_explicitly(self):
        with patch('sparkie.backends.shutil.which', return_value=None):
            with self.assertRaisesRegex(ProviderError, 'not found'):
                await CodexBrain().answer(['test'])

    def test_codex_backend_does_not_require_api_key(self):
        with patch.dict(os.environ, {'SPARKIE_BACKEND':'codex'}, clear=True):
            self.assertIsInstance(configured_brain(), CodexBrain)

    def test_openai_backend_requires_model_and_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'OPENAI_MODEL'):
                configured_brain('openai')
