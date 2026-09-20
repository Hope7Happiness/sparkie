import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { once } from 'node:events';
import { WebSocket } from 'ws';
import { createScriptServer } from './demo-script-server.mjs';

const receive = socket => new Promise((resolve, reject) => {
  const timeout = setTimeout(() => reject(new Error('Timed out waiting for sync')), 3000);
  socket.once('message', raw => { clearTimeout(timeout); resolve(JSON.parse(raw)); });
});
async function start(stateFile, seed) {
  const app = createScriptServer({ stateFile, seed });
  app.server.listen(0, '127.0.0.1'); await once(app.server, 'listening');
  const origin = 'http://127.0.0.1:' + app.server.address().port;
  return { ...app, origin, async client() {
    const socket = new WebSocket(origin.replace('http:', 'ws:') + app.base + 'sync', { origin });
    const snapshot = await receive(socket); return { socket, snapshot };
  } };
}
test('two clients share durable edits; stale same-field writes conflict; only script routes are public', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'sparkie-script-'));
  const stateFile = join(dir, 'state.json');
  let app = await start(stateFile, { 'opening.line.0.1': 'Seeded draft' });
  try {
    const a = await app.client(), b = await app.client();
    assert.equal(a.snapshot.fields['opening.line.0.1'].value, 'Seeded draft');
    for (const path of ['/', '/.env', '/api/status', '/workspace-api', '/s/wrong/', app.base + '../state.json']) {
      assert.equal((await fetch(app.origin + path)).status, 404);
    }
    const key = 'opening.line.0.1', value = '</script><script>window.injected=true</script>\n中文';
    const ack = receive(a.socket), remote = receive(b.socket);
    a.socket.send(JSON.stringify({ type:'edit', id:'a1', key, value, baseRevision:0 }));
    assert.equal((await ack).field.value, value);
    assert.equal((await remote).field.value, value);
    const conflict = receive(b.socket);
    b.socket.send(JSON.stringify({ type:'edit', id:'b1', key, value:'stale text', baseRevision:0 }));
    assert.equal((await conflict).type, 'conflict');
    const otherKey = 'opening.line.1.1';
    const another = receive(b.socket);
    b.socket.send(JSON.stringify({ type:'edit', id:'b2', key:otherKey, value:'Other speaker', baseRevision:0 }));
    assert.equal((await another).field.value, 'Other speaker');
    const invalid = receive(b.socket);
    b.socket.send(JSON.stringify({ type:'edit', id:'bad', key:'__proto__', value:'bad', baseRevision:0 }));
    assert.equal((await invalid).type, 'error');
    const page = await (await fetch(app.origin + app.base)).text();
    const embedded = page.match(/<script id="script-edits" type="application\/json">([\s\S]*?)<\/script>/)[1];
    assert.equal(JSON.parse(embedded).edits[key], value);
    assert.ok(!embedded.includes('<script>'));
    assert.equal(JSON.parse(readFileSync(stateFile)).fields[key].value, value);
    const base = app.base;
    await app.close(); app = await start(stateFile);
    assert.equal(app.base, base);
    const restored = await app.client();
    assert.equal(restored.snapshot.fields[key].value, value);
    assert.equal(restored.snapshot.fields[otherKey].value, 'Other speaker');
  } finally { await app.close(); rmSync(dir, { recursive: true, force: true }); }
});
