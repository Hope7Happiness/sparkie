import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { WebSocketServer, WebSocket } from 'ws';
import { allowedRequest } from './server.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
export function multitrackApi(port = 5178) {
  return {
    name: 'sparkie-multitrack-api', apply: 'serve',
    configureServer(server) {
      const wss = new WebSocketServer({ noServer: true, maxPayload: 12000 });
      let active = null;
      const upgrade = (req, socket, head) => {
        if (new URL(req.url, 'http://localhost').pathname !== '/multitrack-audio') return;
        if (!allowedRequest(req, port, true) || active) {
          socket.end('HTTP/1.1 403 Forbidden\r\n\r\n'); return;
        }
        wss.handleUpgrade(req, socket, head, ws => {
          const child = spawn(path.join(root, '.venv/bin/python'), ['-m', 'sparkie.multitrack_lab'],
            { cwd: root, stdio: ['pipe', 'pipe', 'ignore'] });
          const send = data => {
            if (ws.readyState === WebSocket.OPEN && ws.bufferedAmount < 1024 * 1024) ws.send(JSON.stringify(data));
            else stop();
          };
          let stopped = false;
          const stop = () => {
            if (stopped) return;
            stopped = true;
            if (child.exitCode === null) child.kill('SIGTERM');
            const timer = setTimeout(() => { if (child.exitCode === null) child.kill('SIGKILL'); }, 1500);
            timer.unref();
            ws.close();
          };
          active = stop;
          const lines = createInterface({ input: child.stdout });
          lines.on('line', line => {
            try { send(JSON.parse(line)); }
            catch { send({ type: 'failed', reason: 'invalid_backend_event' }); stop(); }
          });
          ws.on('message', (raw, binary) => {
            try {
              if (binary || child.stdin.writableLength > 256 * 1024) throw new Error('input_backpressure');
              const value = JSON.parse(raw.toString());
              child.stdin.write(JSON.stringify(value) + '\n');
            } catch { send({ type: 'failed', reason: 'invalid_input_or_backpressure' }); stop(); }
          });
          child.stdin.on('error', stop);
          child.on('error', () => { send({ type: 'failed', reason: 'backend_unavailable' }); stop(); if (active === stop) active = null; });
          child.on('exit', code => {
            lines.close();
            if (code !== 0 && !stopped) send({ type: 'failed', reason: 'backend_exited' });
            stopped = true; if (active === stop) active = null; ws.close();
          });
          ws.on('error', stop); ws.on('close', stop);
        });
      };
      server.httpServer.on('upgrade', upgrade);
      const shutdown = () => active?.();
      server.httpServer.once('close', () => {
        shutdown(); wss.close(); server.httpServer.off('upgrade', upgrade);
        process.off('SIGTERM', shutdown); process.off('SIGINT', shutdown);
      });
      process.once('SIGTERM', shutdown); process.once('SIGINT', shutdown);
    },
  };
}
