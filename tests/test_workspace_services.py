"""Local service lifecycle checks; no meeting, provider, or task-worker requests."""
import asyncio
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sparkie.workspace_services import ServiceStartupError, WorkspaceServices, _services


SERVER = r'''
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (b'{"ok": true}' if self.path == '/healthz'
                else '<title>Sparkie · Workspace</title>'.encode())
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args): pass
HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler).serve_forever()
'''


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class WorkspaceServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        vite = self.root / 'frontend/node_modules/vite/bin/vite.js'
        vite.parent.mkdir(parents=True)
        vite.touch()
        self.events, self.children = [], []
        self.backend, self.frontend = free_port(), free_port()
        self.manager = WorkspaceServices(self.root, f'127.0.0.1:{self.backend}', self.frontend,
            lambda kind, **fields: self.events.append((kind, fields)), timeout=2)
        self.spawn = subprocess.Popen
        self.commands = []

    async def asyncTearDown(self):
        for child in self.children:
            await self.manager.stop_failed_child(child)
            if child in _services:
                _services.remove(child)

    def spawn_service(self, command, **kwargs):
        self.commands.append((command, kwargs))
        port = self.backend if 'workspace' in command else self.frontend
        child = self.spawn([sys.executable, '-u', '-c', SERVER, str(port)], **kwargs)
        self.children.append(child)
        return child

    async def test_cold_start_then_reuse_preserves_live_services_and_config(self):
        with patch('sparkie.workspace_services.subprocess.Popen', side_effect=self.spawn_service):
            self.assertTrue(await self.manager.ensure())
            other = WorkspaceServices(self.root, self.manager.server, self.frontend,
                                      self.manager.emit, timeout=2)
            self.assertTrue(await other.ensure())
        self.assertEqual(len(self.children), 2)
        self.assertTrue(all(child.poll() is None for child in self.children))
        readiness = [fields for kind, fields in self.events if kind == 'workspace_service_ready']
        self.assertEqual([event['reused'] for event in readiness], [False, False, True, True])
        self.assertIn('sparkie.primitive', self.commands[0][0])
        for _, kwargs in self.commands:
            self.assertEqual(kwargs['env']['SPARKIE_WEB_PORT'], str(self.frontend))
            self.assertEqual(kwargs['env']['SPARKIE_WORKSPACE_SERVER'], self.manager.server)
            self.assertTrue(kwargs['start_new_session'])

    async def test_simultaneous_launches_start_only_one_pair(self):
        other = WorkspaceServices(self.root, self.manager.server, self.frontend,
                                  self.manager.emit, timeout=3)
        with patch('sparkie.workspace_services.subprocess.Popen', side_effect=self.spawn_service):
            self.assertEqual(await asyncio.gather(self.manager.ensure(), other.ensure()), [True, True])
        self.assertEqual(len(self.children), 2)

    async def test_remote_unavailable_does_not_spawn_local_replacement(self):
        self.manager.server = 'example.invalid:8790'
        self.manager.probe = AsyncMock(return_value=False)
        with patch('sparkie.workspace_services.subprocess.Popen') as spawn:
            self.assertFalse(await self.manager.ensure())
        spawn.assert_not_called()
        self.assertEqual(self.events[-1][1]['reason'], 'remote_workspace_unavailable')

    async def test_wrong_service_and_missing_dependencies_are_explicit(self):
        self.manager.probe = AsyncMock(side_effect=ServiceStartupError('unexpected_service'))
        with patch('sparkie.workspace_services.subprocess.Popen') as spawn:
            self.assertFalse(await self.manager.ensure())
        spawn.assert_not_called()
        self.assertEqual(self.events[-1][1]['reason'], 'unexpected_service')
        self.manager.probe = AsyncMock(side_effect=[True, False])
        (self.root / 'frontend/node_modules/vite/bin/vite.js').unlink()
        with patch('sparkie.workspace_services.subprocess.Popen') as spawn:
            self.assertFalse(await self.manager.ensure())
        spawn.assert_not_called()
        self.assertEqual(self.events[-1][1]['reason'], 'frontend_dependencies_missing')

    async def test_cancellation_terminates_only_the_child_being_started(self):
        self.manager.probe = AsyncMock(return_value=False)
        launched = asyncio.Event()
        def spawn_hung(command, **kwargs):
            child = self.spawn([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
            self.children.append(child)
            launched.set()
            return child
        with patch('sparkie.workspace_services.subprocess.Popen', side_effect=spawn_hung):
            task = asyncio.create_task(self.manager.ensure())
            await asyncio.wait_for(launched.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNotNone(self.children[0].poll())

    async def test_startup_exit_is_reported_without_forwarding_process_output(self):
        self.manager.probe = AsyncMock(return_value=False)
        def fail(command, **kwargs):
            child = self.spawn([sys.executable, '-c', 'raise SystemExit(7)'], **kwargs)
            self.children.append(child)
            return child
        with patch('sparkie.workspace_services.subprocess.Popen', side_effect=fail):
            self.assertFalse(await self.manager.ensure())
        self.assertEqual(self.events[-1][1]['reason'], 'backend_exited')
