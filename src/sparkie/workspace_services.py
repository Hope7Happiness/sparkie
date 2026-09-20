"""Start/reuse local workspace services before a macOS Zoom voice session.

Services outlive the voice session so meeting reports can finish and remain
viewable. Never restart a healthy existing service or start a remote backend.
"""
import asyncio
import ipaddress
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
from urllib.parse import urlsplit

import httpx

# Keep handles while the parent lives; these detached services intentionally
# survive its exit. Reap services that exited before another bootstrap attempt.
_services = []


class ServiceStartupError(RuntimeError):
    pass


class WorkspaceServices:
    def __init__(self, root, server, web_port, emit, *, timeout=15):
        self.root, self.server = Path(root), server
        self.web_port, self.emit, self.timeout = web_port, emit, timeout
        self.runtime = self.root / '.runtime/workspace-services'

    @staticmethod
    def local_host(host):
        if host == 'localhost':
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    async def probe(self, url, kind):
        try:
            async with httpx.AsyncClient(timeout=.75, trust_env=False) as http:
                response = await http.get(url)
            if response.status_code != 200:
                raise ServiceStartupError('unexpected_service')
            if kind == 'backend':
                if response.json() != {'ok': True}:
                    raise ServiceStartupError('unexpected_service')
            elif '<title>Sparkie · Workspace</title>' not in response.text:
                raise ServiceStartupError('unexpected_service')
            return True
        except (httpx.TransportError, OSError):
            return False
        except ValueError:
            raise ServiceStartupError('unexpected_service') from None

    async def stop_failed_child(self, process):
        # Only a process group created by this startup attempt is eligible.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.to_thread(process.wait, timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await asyncio.to_thread(process.wait, timeout=2)

    async def ensure_one(self, kind, url, command):
        if await self.probe(url, kind):
            self.emit('workspace_service_ready', service=kind, reused=True)
            return
        if command is None:
            raise ServiceStartupError('remote_workspace_unavailable')
        if kind == 'frontend' and not (self.root / 'frontend/node_modules/vite/bin/vite.js').is_file():
            raise ServiceStartupError('frontend_dependencies_missing')
        self.emit('workspace_service_starting', service=kind)
        env = {**os.environ, 'SPARKIE_WEB_PORT': str(self.web_port),
               'SPARKIE_WORKSPACE_SERVER': self.server}
        with (self.runtime / f'{kind}.log').open('ab') as log:
            process = subprocess.Popen(command, cwd=self.root, env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True)
        try:
            async with asyncio.timeout(self.timeout):
                while process.poll() is None:
                    if await self.probe(url, kind):
                        _services[:] = [child for child in _services if child.poll() is None]
                        _services.append(process)
                        self.emit('workspace_service_ready', service=kind, reused=False, pid=process.pid)
                        return
                    await asyncio.sleep(.1)
                raise ServiceStartupError(kind + '_exited')
        except BaseException:
            await self.stop_failed_child(process)
            raise

    async def ensure(self):
        """Return readiness; fixed diagnostics explain failures without stopping voice."""
        try:
            import fcntl
            parsed = urlsplit('http://' + self.server)
            if (not parsed.hostname or parsed.username or parsed.password or
                    parsed.path or parsed.query or parsed.fragment):
                raise ServiceStartupError('invalid_workspace_address')
            port = parsed.port or 80
            self.web_port = int(self.web_port)
            if not 1 <= self.web_port <= 65535:
                raise ServiceStartupError('invalid_web_port')
            self.runtime.mkdir(parents=True, exist_ok=True)
            # Concurrent local launches cannot both decide to own the same port.
            with (self.runtime / 'startup.lock').open('a') as lock:
                async with asyncio.timeout(self.timeout):
                    while True:
                        try:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except BlockingIOError:
                            await asyncio.sleep(.1)
                try:
                    backend = ([sys.executable, '-m', 'sparkie.primitive', 'workspace',
                                '--host', parsed.hostname, '--port', str(port)]
                               if self.local_host(parsed.hostname) else None)
                    await self.ensure_one('backend', f'http://{self.server}/healthz', backend)
                    node = shutil.which('node')
                    frontend = [node or 'node', str(self.root / 'frontend/node_modules/vite/bin/vite.js'),
                                str(self.root / 'frontend'),
                                '--config', str(self.root / 'frontend/vite.config.mjs')]
                    await self.ensure_one('frontend', f'http://127.0.0.1:{self.web_port}/workspace.html', frontend)
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
            return True
        except Exception as exc:
            reason = str(exc) if isinstance(exc, ServiceStartupError) else type(exc).__name__
            self.emit('workspace_services_failed', reason=reason,
                      hint='Check .runtime/workspace-services/*.log; install frontend dependencies with npm --prefix frontend ci if missing. Voice can continue without sharing.')
            return False
