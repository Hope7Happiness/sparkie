/* Loaded only by the shared rehearsal server. Standalone downloads stay local. */
(() => {
  const status = document.querySelector('#edit-status');
  const help = document.querySelector('.edit-help');
  help.firstChild.textContent = 'Shared script: click a line to edit it for everyone. Role views and timers remain independent.';
  const conflicts = document.createElement('div');
  conflicts.className = 'edit-help';
  help.after(conflicts);
  const storageKey = draftKey + ':pending';
  const pending = new Map();
  let fields = {}, socket, ready = false, timer, sequence = 0;
  const clientId = Math.random().toString(36).slice(2);
  let storageAvailable = true;
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    for (const [key, value] of Object.entries(saved)) {
      if (editableFields.has(key) && typeof value.value === 'string' && Number.isSafeInteger(value.baseRevision)) {
        pending.set(key, { value: value.value, baseRevision: value.baseRevision });
      }
    }
  } catch { storageAvailable = false; }
  function savePending() {
    try { localStorage.setItem(storageKey, JSON.stringify(Object.fromEntries([...pending].map(([key, value]) => [key, {
      value: value.value, baseRevision: value.baseRevision,
    }])))); } catch { storageAvailable = false; }
  }
  function showValue(key, value) {
    applyEdits({ [key]: value });
    const element = document.querySelector('[data-edit="' + key + '"]');
    if (element && element.innerText !== value) element.textContent = value;
    document.querySelector('#print-content').innerHTML = printHTML();
  }
  function paint() {
    const conflictEntries = [...pending].filter(([, item]) => item.conflict);
    status.textContent = !ready ? ' Connecting; unsynced edits are preserved and will resume on reconnect.' : conflictEntries.length
      ? ' This line has conflicting edits. Choose which version to keep below.' : pending.size ? ' Syncing…' : ' Synced and visible to everyone.';
    if (!storageAvailable && pending.size) status.textContent += ' The browser cannot save drafts. Keep this page open or download a backup.';
    conflicts.replaceChildren();
    for (const [key, item] of conflictEntries) {
      const row = document.createElement('div');
      row.style.cssText = 'padding:12px;border:1px solid #b58c60;margin:8px 0;white-space:pre-wrap;overflow-wrap:anywhere';
      const label = document.createElement('p');
      const fieldElement = document.querySelector('[data-edit="' + key + '"]');
      const sceneTitle = fieldElement?.closest('.scene')?.querySelector('h2')?.textContent || '';
      const turn = fieldElement?.closest('.line')?.querySelector('.turn')?.textContent || 'Fallback / Example';
      label.textContent = sceneTitle + ' · ' + turn + '\nYour version: ' + item.value + '\nShared version: ' + fields[key].value;
      row.append(label);
      for (const [title, mine] of [['Use shared version', false], ['Use my version', true]]) {
        const button = document.createElement('button');
        button.textContent = title;
        button.onclick = () => {
          if (mine) { item.baseRevision = fields[key].revision; item.conflict = false; item.inflight = null; }
          else { pending.delete(key); showValue(key, fields[key].value); }
          savePending(); paint(); flush();
        };
        row.append(button);
      }
      conflicts.append(row);
    }
  }
  function flush() {
    if (!ready || socket.readyState !== WebSocket.OPEN) return;
    for (const [key, item] of pending) {
      if (item.conflict || item.inflight) continue;
      const id = clientId + ':' + (++sequence);
      item.inflight = { id, value: item.value };
      socket.send(JSON.stringify({ type: 'edit', key, value: item.value, baseRevision: item.baseRevision, id }));
    }
  }
  document.querySelector('#script-board').addEventListener('input', event => {
    const element = event.target.closest('[data-edit]');
    if (!element || !fields[element.dataset.edit]) return;
    const key = element.dataset.edit;
    const item = pending.get(key) || { baseRevision: fields[key].revision };
    item.value = element.innerText.replace(/\r\n/g, '\n');
    pending.set(key, item);
    savePending(); paint(); clearTimeout(timer); timer = setTimeout(flush, 120);
  });
  // Content is rendered before the first snapshot, but writes need known revisions.
  document.querySelectorAll('[data-edit]').forEach(element => element.contentEditable = 'false');
  function connect() {
    ready = false; paint();
    const url = new URL('sync', location.href);
    url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(url);
    socket.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.type === 'snapshot') {
        fields = message.fields; ready = true;
        for (const [key, field] of Object.entries(fields)) {
          const item = pending.get(key);
          if (item && item.value !== field.value) {
            item.inflight = null;
            item.conflict = item.baseRevision !== field.revision;
            showValue(key, item.value);
          } else { pending.delete(key); showValue(key, field.value); }
        }
        document.querySelectorAll('[data-edit]').forEach(element => element.contentEditable = 'plaintext-only');
      } else if (message.type === 'update') {
        const { key, field, id } = message;
        fields[key] = field;
        const item = pending.get(key);
        if (item?.inflight?.id === id) {
          if (item.value === field.value) pending.delete(key);
          else { item.baseRevision = field.revision; item.inflight = null; }
        }
        if (!pending.has(key)) showValue(key, field.value);
      } else if (message.type === 'conflict') {
        fields[message.key] = message.field;
        const item = pending.get(message.key);
        if (item) { item.inflight = null; item.conflict = true; }
      } else if (message.type === 'error') {
        status.textContent = message.message;
        return;
      }
      savePending(); paint(); flush();
    };
    socket.onclose = () => {
      ready = false;
      for (const item of pending.values()) item.inflight = null;
      paint(); setTimeout(connect, 1500);
    };
    socket.onerror = () => socket.close();
  }
  window.addEventListener('beforeunload', event => {
    if (pending.size) { event.preventDefault(); event.returnValue = ''; }
  });
  connect();
})();
