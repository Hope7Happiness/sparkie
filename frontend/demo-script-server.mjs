import { createServer } from 'node:http';
import { readFileSync, writeFileSync, renameSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { WebSocketServer, WebSocket } from 'ws';

const pagePath = fileURLToPath(new URL('../presentation/demo-script.html', import.meta.url));
const clientPath = fileURLToPath(new URL('./demo-script-sync.js', import.meta.url));
const json = value => JSON.stringify(value).replace(/</g, '\\u003c');

export function createScriptServer({ stateFile, seed = {} }) {
  const html = readFileSync(pagePath, 'utf8');
  const scenes = JSON.parse(html.match(/const sceneData = (\[[\s\S]*?\n\]);/)[1]);
  const defaults = {};
  for (const scene of scenes) {
    scene.lines.forEach((line, i) => [1, 2, 3].forEach(field => { defaults[scene.id + '.line.' + i + '.' + field] = line[field]; }));
    if (scene.example !== undefined) defaults[scene.id + '.example'] = scene.example;
    if (scene.filler) defaults[scene.id + '.filler'] = scene.filler[1];
    if (scene.recovery !== undefined) defaults[scene.id + '.recovery'] = scene.recovery;
  }
  let state = existsSync(stateFile) ? JSON.parse(readFileSync(stateFile, 'utf8')) : {
    token: randomBytes(24).toString('hex'), revision: 0,
    fields: Object.fromEntries(Object.entries(defaults).map(([key, value]) => [key, {
      value: typeof seed[key] === 'string' ? seed[key] : value, revision: 0,
    }])),
  };
  function persist(next) {
    mkdirSync(dirname(stateFile), { recursive: true });
    writeFileSync(stateFile + '.tmp', JSON.stringify(next), { mode: 0o600 });
    renameSync(stateFile + '.tmp', stateFile);
  }
  persist(state);
  const base = '/s/' + state.token + '/';
  const sockets = new WebSocketServer({ noServer: true, maxPayload: 128 * 1024 });
  function send(socket, value) { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(value)); }
  function broadcast(value) { for (const socket of sockets.clients) send(socket, value); }
  const server = createServer((req, res) => {
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('X-Robots-Tag', 'noindex, nofollow');
    if (req.method !== 'GET') { res.writeHead(405).end(); return; }
    const pathname = new URL(req.url, 'http://localhost').pathname;
    if (pathname === base) {
      const draft = { id: 'shared-' + state.token, shared: true, edits: Object.fromEntries(Object.entries(state.fields).map(([k, field]) => [k, field.value])) };
      const page = html.replace(/(<script id="script-edits" type="application\/json">)[\s\S]*?(<\/script>)/,
        (_, start, end) => start + json(draft) + end)
        .replace('</body>', '<script src="' + base + 'sync.js"></script></body>');
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' }).end(page);
    } else if (pathname === base + 'sync.js') {
      res.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8' }).end(readFileSync(clientPath));
    } else { res.writeHead(404).end('Not found'); }
  });
  server.on('upgrade', (req, socket, head) => {
    const pathname = new URL(req.url, 'http://localhost').pathname;
    const origin = req.headers.origin;
    if (pathname !== base + 'sync' || ![ 'http://' + req.headers.host, 'https://' + req.headers.host ].includes(origin)) {
      socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n'); return;
    }
    sockets.handleUpgrade(req, socket, head, ws => sockets.emit('connection', ws));
  });
  sockets.on('connection', socket => {
    send(socket, { type: 'snapshot', fields: state.fields });
    socket.on('error', () => {});
    socket.on('message', raw => {
      let message;
      try { message = JSON.parse(raw); } catch { send(socket, { type: 'error', message: 'Invalid request' }); return; }
      if (!message || message.type !== 'edit' || !Object.hasOwn(defaults, message.key) ||
          typeof message.value !== 'string' || message.value.length > 20000 ||
          !Number.isSafeInteger(message.baseRevision) || typeof message.id !== 'string' || message.id.length > 100) {
        send(socket, { type: 'error', message: 'Cannot save: invalid request or script text exceeds 20,000 characters.' }); return;
      }
      const current = state.fields[message.key];
      if (message.baseRevision !== current.revision && message.value !== current.value) {
        send(socket, { type: 'conflict', key: message.key, field: current, id: message.id }); return;
      }
      const field = { value: message.value, revision: state.revision + 1 };
      const next = { ...state, revision: field.revision, fields: { ...state.fields, [message.key]: field } };
      try { persist(next); } catch {
        send(socket, { type: 'error', message: 'Save failed. Keep this page open and download a backup.' }); return;
      }
      state = next;
      broadcast({ type: 'update', key: message.key, field, id: message.id });
    });
  });
  return { server, base, close: async () => {
    for (const socket of sockets.clients) socket.terminate();
    await new Promise(resolve => sockets.close(resolve));
    await new Promise(resolve => server.close(resolve));
  } };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const stateFile = resolve(process.env.SPARKIE_SCRIPT_STATE || '.runtime/demo-script-shared.json');
  const seed = process.env.SPARKIE_SCRIPT_SEED ? JSON.parse(readFileSync(process.env.SPARKIE_SCRIPT_SEED, 'utf8')) : {};
  const app = createScriptServer({ stateFile, seed });
  const port = Number(process.env.SPARKIE_SCRIPT_PORT || 5193);
  app.server.listen(port, '127.0.0.1', () => console.log('Shared script: http://127.0.0.1:' + port + app.base));
}
