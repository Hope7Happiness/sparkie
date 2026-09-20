import './realtime.css';
import './workspace.css';

const $ = id => document.getElementById(id);
const state = {
  socket: null, server: null, workspaceId: null, activeArtifact: null,
  artifacts: new Map(), tasks: new Map(), hydrated: new Set(), utterances: 0,
};

const setState = text => { $('state').textContent = text; };
const fail = message => { $('error').textContent = message; setState('Connection failed'); };

const bump = id => { $(id).textContent = String(Number($(id).textContent) + 1); };

function entry(container, small, text, cls = '') {
  const box = document.createElement('div');
  box.className = `entry ${cls}`;
  const meta = document.createElement('small');
  meta.textContent = small;
  const body = document.createElement('p');
  body.textContent = text;
  box.append(meta, body);
  const feed = $(container);
  feed.querySelector('.empty')?.remove();
  feed.append(box);
  feed.scrollTop = feed.scrollHeight;
  return box;
}

/* ---------------------------------------------------------------- markdown --
   A compact markdown renderer that builds DOM nodes directly. Nothing is ever
   assigned through innerHTML, so artifact content can never inject markup —
   every span of text lands in a textContent, every href passes safeUrl(). */

const SAFE_URL = /^(https?:\/\/|mailto:)/i;
const INLINE = new RegExp([
  '`([^`]+)`',                                   // 1 inline code
  '\\*\\*([^*]+?)\\*\\*',                        // 2 **bold**
  '(?<![\\w\\\\])__([^_]+?)__(?![\\w])',         // 3 __bold__
  '\\*([^*\\n]+?)\\*',                           // 4 *italic*
  '(?<![\\w\\\\])_([^_\\n]+?)_(?![\\w])',        // 5 _italic_
  '\\[([^\\]]*)\\]\\(([^)\\s]+)\\)',             // 6 label / 7 href
  '(<?https?://[^\\s<>)]+>?)',                   // 8 bare url
].join('|'), 'g');

function safeUrl(raw, dataPrefix) {
  const url = String(raw ?? '').trim();
  if (SAFE_URL.test(url)) return url;
  if (url.startsWith('/') && !url.startsWith('//')) return url;
  if (dataPrefix && new RegExp(`^data:${dataPrefix}`, 'i').test(url)) return url;
  return null;
}

function link(url, label) {
  const anchor = document.createElement('a');
  anchor.href = url; anchor.textContent = label;
  anchor.target = '_blank'; anchor.rel = 'noopener noreferrer';
  return anchor;
}

function inline(text, parent) {
  const source = String(text ?? '');
  let cursor = 0;
  for (const match of source.matchAll(INLINE)) {
    const [full, code, bold1, bold2, em1, em2, label, href, bare] = match;
    if (match.index > cursor) parent.append(source.slice(cursor, match.index));
    if (code != null) {
      const el = document.createElement('code'); el.textContent = code; parent.append(el);
    } else if (bold1 ?? bold2) {
      const el = document.createElement('strong'); el.textContent = bold1 ?? bold2; parent.append(el);
    } else if (em1 ?? em2) {
      const el = document.createElement('em'); el.textContent = em1 ?? em2; parent.append(el);
    } else if (bare != null) {
      const url = safeUrl(bare.replace(/^<|>$/g, ''));
      parent.append(url ? link(url, url) : bare);
    } else {
      const url = safeUrl(href);
      parent.append(url ? link(url, label || url) : `${label || ''}(${href})`);
    }
    cursor = match.index + full.length;
  }
  if (cursor < source.length) parent.append(source.slice(cursor));
  return parent;
}

function renderMarkdown(source) {
  const root = document.createElement('div');
  root.className = 'md';
  const lines = String(source ?? '').split(/\r?\n/);
  const stack = [];          // open lists, innermost last: {indent, ordered, el}
  let paragraph = null;
  let index = 0;
  const closeBlocks = () => { paragraph = null; stack.length = 0; };

  const openList = (indent, ordered) => {
    while (stack.length && stack[stack.length - 1].indent > indent) stack.pop();
    const top = stack[stack.length - 1];
    if (top && top.indent === indent) {
      if (top.ordered === ordered) return top.el;
      stack.pop();
    }
    const parent = stack[stack.length - 1];
    const el = document.createElement(ordered ? 'ol' : 'ul');
    if (parent && parent.indent < indent) (parent.el.lastElementChild || parent.el).append(el);
    else { stack.length = 0; root.append(el); }
    stack.push({ indent, ordered, el });
    return el;
  };

  while (index < lines.length) {
    const line = lines[index].replace(/\s+$/, '');

    const fence = line.match(/^\s{0,3}```\s*([\w+#.-]*)\s*$/);
    if (fence) {
      closeBlocks();
      const body = [];
      for (index += 1; index < lines.length && !/^\s{0,3}```\s*$/.test(lines[index]); index += 1) {
        body.push(lines[index]);
      }
      index += 1;
      const pre = document.createElement('pre');
      const code = document.createElement('code');
      if (fence[1]) { code.dataset.lang = fence[1]; pre.dataset.lang = fence[1]; }
      code.textContent = body.join('\n');
      pre.append(code); root.append(pre);
      continue;
    }

    if (!line.trim()) { closeBlocks(); index += 1; continue; }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.*)$/);
    if (heading) {
      closeBlocks();
      const el = document.createElement(`h${heading[1].length}`);
      inline(heading[2].replace(/\s+#+\s*$/, ''), el);
      root.append(el); index += 1; continue;
    }

    if (/^\s{0,3}([-*_])\s*(\1\s*){2,}$/.test(line)) {
      closeBlocks(); root.append(document.createElement('hr')); index += 1; continue;
    }

    if (/^\s{0,3}>\s?/.test(line)) {
      closeBlocks();
      const quoted = [];
      while (index < lines.length) {
        const match = lines[index].match(/^\s{0,3}>\s?(.*)$/);
        if (!match) break;
        quoted.push(match[1]); index += 1;
      }
      const quote = document.createElement('blockquote');
      quote.append(renderMarkdown(quoted.join('\n')));
      root.append(quote); continue;
    }

    const item = line.match(/^(\s*)(?:[-*+]|(\d{1,9})[.)])\s+(.*)$/);
    if (item) {
      paragraph = null;
      const list = openList(Math.floor(item[1].length / 2), item[2] != null);
      if (item[2] != null && !list.childElementCount && Number(item[2]) !== 1) list.start = Number(item[2]);
      const li = document.createElement('li');
      inline(item[3].replace(/^\[([ xX])\]\s+/, (_, box) => (box === ' ' ? '☐ ' : '☑ ')), li);
      list.append(li); index += 1; continue;
    }

    // Pipe table: header row, |---|---| delimiter, then body rows.
    if (/^\s*\|.*\|/.test(line) && index + 1 < lines.length &&
        /^\s*\|?(\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$/.test(lines[index + 1])) {
      closeBlocks();
      const cells = row => row.trim().replace(/^\|/, '').replace(/\|$/, '')
        .split('|').map(cell => cell.trim());
      const table = document.createElement('table');
      const head = document.createElement('tr');
      for (const cell of cells(line)) {
        const th = document.createElement('th');
        inline(cell, th); head.append(th);
      }
      const thead = document.createElement('thead');
      thead.append(head); table.append(thead);
      const tbody = document.createElement('tbody');
      for (index += 2; index < lines.length && /^\s*\|.*\|/.test(lines[index]); index += 1) {
        const tr = document.createElement('tr');
        for (const cell of cells(lines[index])) {
          const td = document.createElement('td');
          inline(cell, td); tr.append(td);
        }
        tbody.append(tr);
      }
      table.append(tbody); root.append(table); continue;
    }

    if (stack.length && /^\s{2,}\S/.test(line)) {
      const li = stack[stack.length - 1].el.lastElementChild;
      if (li) { li.append(' '); inline(line.trim(), li); index += 1; continue; }
    }

    if (!paragraph) { stack.length = 0; paragraph = document.createElement('p'); root.append(paragraph); }
    else paragraph.append(' ');
    inline(line.trim(), paragraph);
    index += 1;
  }
  return root;
}

/* ---------------------------------------------------------------- artifacts */

const KIND_LABEL = {
  report: 'report', markdown: 'markdown', image: 'image',
  pdf: 'pdf', url: 'link', demo: 'demo', json: 'json', markdown_url: 'markdown',
};

// A URL that serves markdown: *.md / *.markdown paths, or a data:text/markdown URI.
function isMarkdownUrl(raw) {
  const url = String(raw ?? '').trim();
  return /^data:text\/markdown/i.test(url) || /\.(md|markdown|mdown)([?#].*)?$/i.test(url);
}

// What shape does the payload actually carry? Drives both the stage renderer
// and the little coloured badge in the artifact list.
function contentShape(content) {
  if (typeof content === 'string') return content.trim() ? 'markdown' : null;
  if (!content || typeof content !== 'object') return null;
  if (typeof content.markdown === 'string' && content.markdown.trim()) return 'markdown';
  if (typeof content.answer === 'string' && content.answer.trim()) return 'markdown';
  if (isMarkdownUrl(content.markdown_url) || isMarkdownUrl(content.url)) return 'markdown_url';
  if (content.image) return 'image';
  if (content.pdf) return 'pdf';
  if (content.url) return 'url';
  return 'json';
}

// URL-backed artifacts store a content_url instead of inline content_json.
function artifactContent(artifact) {
  const content = artifact?.content;
  if (content == null || content === '') {
    return artifact?.content_url ? { url: artifact.content_url } : content;
  }
  return content;
}

function artifactKind(artifact) {
  const shape = contentShape(artifactContent(artifact));
  if (shape && shape !== 'json' && shape !== 'markdown') return shape;
  const declared = artifact?.type;
  if (declared && declared !== 'artifact.ready' && KIND_LABEL[declared]) return declared;
  return shape || 'report';
}

function markdownBody(artifact) {
  const content = artifact.content;
  if (typeof content === 'string') return content;
  if (content && typeof content === 'object') {
    if (typeof content.markdown === 'string') return content.markdown;
    if (typeof content.answer === 'string') return content.answer;
    if (content.image) return `![image](${content.image})`;
    if (content.pdf) return `[PDF](${content.pdf})`;
    if (content.markdown_url) return `<${content.markdown_url}>`;
    if (content.url) return `<${content.url}>`;
    return `\`\`\`json\n${JSON.stringify(content, null, 2)}\n\`\`\``;
  }
  return content == null ? '' : String(content);
}

function saveBlob(filename, text, mime) {
  const anchor = document.createElement('a');
  anchor.href = URL.createObjectURL(new Blob([text], { type: mime }));
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(anchor.href);
}

function downloadArtifact(artifact) {
  const markdown = `# ${artifact.title || 'artifact'}\n\n${artifact.summary || ''}\n\n${markdownBody(artifact)}\n`;
  saveBlob(`${artifact.artifact_id}.md`, markdown, 'text/markdown');
}

function downloadJson(artifact) {
  const payload = {
    artifact_id: artifact.artifact_id, type: artifactKind(artifact),
    title: artifact.title || '', summary: artifact.summary || '',
    content: artifact.content ?? null,
  };
  saveBlob(`${artifact.artifact_id}.json`, JSON.stringify(payload, null, 2), 'application/json');
}

// Browsers refuse to navigate iframes/embeds to data: URIs — reblob them.
const blobUrls = [];
function mediaUrl(raw, dataPrefix) {
  const url = safeUrl(raw, dataPrefix);
  if (!url || !url.startsWith('data:')) return url;
  try {
    const [head, body] = url.split(',', 2);
    const mime = head.slice(5).split(';')[0] || 'application/octet-stream';
    const bytes = head.includes(';base64')
      ? Uint8Array.from(atob(body), c => c.charCodeAt(0))
      : new TextEncoder().encode(decodeURIComponent(body));
    const blob = URL.createObjectURL(new Blob([bytes], { type: mime }));
    blobUrls.push(blob);
    return blob;
  } catch { return null; }
}

function mediaFrame(tag, url, title, { sandbox = true } = {}) {
  const frame = document.createElement(tag);
  frame.src = url;
  frame.title = title;
  if (tag === 'iframe') {
    frame.loading = 'lazy';
    frame.referrerPolicy = 'no-referrer';
    // Chrome's PDF viewer refuses to render inside a sandboxed frame; our own
    // blob URLs are trusted content, so PDF frames skip the sandbox.
    if (sandbox) frame.setAttribute('sandbox', 'allow-scripts allow-popups allow-forms');
  }
  return frame;
}

function jsonFallback(content, note) {
  const wrap = document.createElement('div');
  if (note) {
    const warning = document.createElement('p');
    warning.className = 'stage-note';
    warning.textContent = note;
    wrap.append(warning);
  }
  const pre = document.createElement('pre');
  pre.className = 'stage-json';
  pre.textContent = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
  wrap.append(pre);
  return wrap;
}

// Renders artifact.content by shape and returns the shape actually used.
function renderContent(artifact, mount) {
  const content = artifactContent(artifact);
  if (content == null || content === '') return null;

  const shape = contentShape(content);

  if (shape === 'markdown') {
    const body = typeof content === 'string' ? content : (content.markdown ?? content.answer);
    const article = document.createElement('div');
    article.className = 'stage-md';
    article.append(renderMarkdown(body));
    mount.append(article);
    return 'markdown';
  }

  if (shape === 'markdown_url') {
    // Markdown served by URL — fetch it and render inline like inline markdown.
    const raw = content.markdown_url ?? content.url;
    let url = mediaUrl(raw, 'text/markdown');
    if (!url) {
      const safe = safeUrl(raw);
      if (!safe) { mount.append(jsonFallback(content, 'Unsafe markdown URL — showing raw data.')); return 'json'; }
      // Relative paths live on the workspace backend, not the vite origin.
      url = safe.startsWith('/') && state.server ? `${state.server}${safe}` : safe;
    }
    const article = document.createElement('div');
    article.className = 'stage-md';
    mount.append(article);
    const note = document.createElement('p');
    note.className = 'stage-note';
    note.textContent = 'Loading markdown…';
    article.append(note);
    fetch(url).then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.text();
    }).then(text => {
      if (!article.isConnected) return;
      note.remove();
      article.append(renderMarkdown(text));
    }).catch(() => {
      if (!article.isConnected) return;
      note.textContent = 'Cannot embed — ';
      note.append(link(url, 'open .md in a new tab'));
    });
    return 'markdown';
  }

  if (shape === 'image') {
    const url = safeUrl(content.image, 'image/');
    if (!url) { mount.append(jsonFallback(content, 'Unsafe image URL — showing raw data.')); return 'json'; }
    const box = document.createElement('div');
    box.className = 'stage-media';
    const img = document.createElement('img');
    img.src = url;
    img.alt = content.alt || artifact.title || 'artifact image';
    box.append(img);
    if (content.caption) {
      const caption = document.createElement('p');
      caption.className = 'stage-caption';
      caption.textContent = content.caption;
      box.append(caption);
    }
    mount.append(box);
    return 'image';
  }

  if (shape === 'pdf') {
    const url = mediaUrl(content.pdf, 'application/pdf');
    if (!url) { mount.append(jsonFallback(content, 'Unsafe PDF URL — showing raw data.')); return 'json'; }
    const box = document.createElement('div');
    box.className = 'stage-media stage-media-tall';
    box.append(mediaFrame('iframe', url, artifact.title || 'PDF', { sandbox: false }));
    const row = document.createElement('p');
    row.className = 'stage-caption';
    row.append('Preview unavailable? ', link(url, 'open PDF in a new tab'));
    box.append(row);
    mount.append(box);
    return 'pdf';
  }

  if (shape === 'url') {
    const url = safeUrl(content.url);
    if (!url) { mount.append(jsonFallback(content, 'Unsafe link URL — showing raw data.')); return 'json'; }
    const box = document.createElement('div');
    box.className = 'stage-media stage-media-tall';
    box.append(mediaFrame('iframe', url, content.title || artifact.title || url));
    const row = document.createElement('p');
    row.className = 'stage-caption';
    row.append('Source: ', link(url, content.title || url));
    box.append(row);
    mount.append(box);
    return 'url';
  }

  mount.append(jsonFallback(content));
  return 'json';
}

function renderStage(artifact) {
  const stage = $('stage');
  stage.textContent = '';
  blobUrls.splice(0).forEach(url => URL.revokeObjectURL(url));
  if (!artifact) return;

  const card = document.createElement('div');
  card.className = 'artifact-stage';
  const kind = artifactKind(artifact);
  card.dataset.kind = kind;

  const title = document.createElement('h3');
  title.textContent = artifact.title || '(untitled)';

  const badge = document.createElement('span');
  badge.className = 'type-badge';
  badge.dataset.kind = kind;
  badge.textContent = KIND_LABEL[kind] || kind;

  const head = document.createElement('div');
  head.className = 'stage-head';
  head.append(badge);

  const summary = document.createElement('p');
  summary.className = 'stage-summary';
  summary.textContent = artifact.summary || '';

  card.append(title, head, summary);

  const body = document.createElement('div');
  body.className = 'stage-content';
  const shape = renderContent(artifact, body);
  if (shape) card.append(body);

  const actions = document.createElement('div');
  actions.className = 'stage-actions';
  const full = document.createElement('button');
  full.type = 'button'; full.className = 'secondary'; full.textContent = 'Present';
  full.onclick = () => openOverlay(artifact);
  const download = document.createElement('button');
  download.type = 'button'; download.className = 'secondary'; download.textContent = 'Download .md';
  download.onclick = () => downloadArtifact(artifact);
  actions.append(full, download);
  if (shape && shape !== 'markdown') {
    const json = document.createElement('button');
    json.type = 'button'; json.className = 'secondary'; json.textContent = 'Download .json';
    json.onclick = () => downloadJson(artifact);
    actions.append(json);
  }
  card.append(actions);

  stage.append(card);
}

/* ------------------------------------------------------- fullscreen overlay */

function overlayOpen() {
  const overlay = $('artifact-overlay');
  return overlay && !overlay.hidden;
}

function renderOverlay(artifact) {
  const card = $('overlay-card');
  card.textContent = '';
  const title = document.createElement('h2');
  title.className = 'overlay-title';
  title.textContent = artifact.title || '(untitled)';
  const summary = document.createElement('p');
  summary.className = 'stage-summary';
  summary.textContent = artifact.summary || '';
  const body = document.createElement('div');
  body.className = 'overlay-content';
  renderContent(artifact, body);
  card.append(title, summary, body);
}

function openOverlay(artifact) {
  if (!artifact) return;
  renderOverlay(artifact);
  $('artifact-overlay').hidden = false;
}

function closeOverlay() {
  $('artifact-overlay').hidden = true;
}

// artifact.ready events only carry metadata; pull the body from the documented
// GET /api/artifacts/<id> so the stage and the type badge reflect real content.
async function hydrateArtifact(id) {
  const known = state.artifacts.get(id);
  if (!known || known.content !== undefined || !state.server || state.hydrated.has(id)) return;
  state.hydrated.add(id);
  try {
    const response = await fetch(`${state.server}/api/artifacts/${id}`);
    if (!response.ok) return;
    const full = await response.json();
    const merged = { ...state.artifacts.get(id), ...full, artifact_id: id };
    state.artifacts.set(id, merged);
    paintArtifactCard(merged);
    if (state.activeArtifact === id) {
      renderStage(merged);
      if (overlayOpen()) renderOverlay(merged);
    }
  } catch {
    /* metadata-only view stays on screen */
  }
}

// artifact.ready only carries metadata, so hydrate first: presenting an empty
// shell mid-generation looks like a broken artifact.
async function presentArtifact(id, { overlay = false } = {}) {
  state.activeArtifact = id;
  document.querySelectorAll('.artifact').forEach(el =>
    el.classList.toggle('active', el.dataset.artifact === id));
  if (!state.artifacts.get(id)) return;
  if (state.artifacts.get(id).content === undefined) await hydrateArtifact(id);
  const artifact = state.artifacts.get(id);
  renderStage(artifact);
  if (overlay || overlayOpen()) openOverlay(artifact);
}

function paintArtifactCard(artifact) {
  const card = document.querySelector(`[data-artifact="${artifact.artifact_id}"]`);
  if (!card) return;
  const kind = artifactKind(artifact);
  card.querySelector('h3').textContent = artifact.title || '(untitled)';
  const badge = card.querySelector('.type-badge');
  badge.dataset.kind = kind;
  badge.textContent = KIND_LABEL[kind] || kind;
  card.querySelector('small').textContent = artifact.summary || '';
  card.classList.toggle('active', artifact.artifact_id === state.activeArtifact);
}

function upsertArtifact(event) {
  const id = event.artifact_id;
  const artifact = { ...(state.artifacts.get(id) || {}), ...event, artifact_id: id };
  state.artifacts.set(id, artifact);
  let card = document.querySelector(`[data-artifact="${id}"]`);
  if (!card) {
    card = document.createElement('div');
    card.className = 'task artifact';
    card.dataset.artifact = id;
    const title = document.createElement('h3');
    const row = document.createElement('div');
    row.className = 'card-meta';
    const badge = document.createElement('span');
    badge.className = 'type-badge';
    const meta = document.createElement('small');
    row.append(badge, meta);
    const open = document.createElement('button');
    open.type = 'button'; open.className = 'secondary'; open.textContent = 'Present';
    open.onclick = () => presentArtifact(id, { overlay: true });
    card.append(title, row, open);
    $('artifacts').querySelector('.empty')?.remove();
    $('artifacts').append(card);
    bump('artifact-count');
  }
  paintArtifactCard(artifact);
  if (artifact.content === undefined) hydrateArtifact(id);
}

/* -------------------------------------------------------------------- tasks */

const STATUS_FROM_EVENT = {
  'task.queued': 'queued', 'task.started': 'running',
  'task.completed': 'completed', 'task.failed': 'failed',
  'task.cancelled': 'cancelled',
};
const STATUS_LABEL = { queued: 'Queued', running: 'Running…', completed: 'Done', failed: 'Failed', cancelled: 'Cancelled' };

function taskStatus(event) {
  if (event.status && STATUS_LABEL[event.status]) return event.status;
  return STATUS_FROM_EVENT[event.type] || 'queued';
}

function upsertTask(event) {
  const id = event.task_id;
  const status = taskStatus(event);
  const task = { ...(state.tasks.get(id) || {}), ...event, status };
  state.tasks.set(id, task);
  let card = document.querySelector(`[data-task="${id}"]`);
  if (!card) {
    card = document.createElement('div');
    card.className = 'task';
    card.dataset.task = id;
    const title = document.createElement('h3');
    const meta = document.createElement('small');
    meta.className = 'status-pill';
    card.append(title, meta);
    $('tasks').querySelector('.empty')?.remove();
    $('tasks').append(card);
    bump('task-count');
  }
  card.dataset.status = status;
  card.className = `task status-${status}`;
  card.querySelector('h3').textContent = task.instruction || task.title || id;
  const reason = task.error_type || task.error;
  card.querySelector('small').textContent =
    status === 'failed' ? `${STATUS_LABEL.failed} · ${reason || 'unknown error'}`
    : status === 'running' && task.progress ? `Running… · ${task.progress}`
    : STATUS_LABEL[status];
  const cancel = card.querySelector('.task-cancel');
  if ((status === 'running' || status === 'queued') && !cancel) {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'task-cancel quiet'; button.textContent = 'Cancel';
    button.onclick = () => state.socket?.readyState === WebSocket.OPEN &&
      state.socket.send(JSON.stringify({ type: 'cancel_task', task_id: id }));
    card.append(button);
  } else if (status !== 'running' && status !== 'queued' && cancel) cancel.remove();
}

/* ------------------------------------------------------------------ session */

function loadSnapshot(snapshot) {
  for (const row of snapshot.transcript || []) {
    entry('transcript', row.speaker || row.source, row.text);
    state.utterances += 1;
  }
  $('utterance-count').textContent = String(state.utterances);
  for (const task of snapshot.tasks || []) {
    upsertTask({
      task_id: task.task_id, instruction: task.instruction,
      status: task.status, error_type: task.error,
    });
  }
  for (const artifact of snapshot.artifacts || []) upsertArtifact(artifact);
  const active = snapshot.state?.active_artifact_id;
  if (active && state.artifacts.has(active)) presentArtifact(active);
}

function onEvent(event) {
  switch (event.type) {
    case 'utterance':
      entry('transcript', event.speaker || event.source, event.text);
      bump('utterance-count');
      break;
    case 'agent.respond':
      entry('transcript', 'sparkie', event.text || `→ ${event.request || ''}`, 'sparkie');
      break;
    case 'task.started': case 'task.completed': case 'task.failed': case 'task.cancelled':
    case 'task.updated':
      upsertTask(event);
      break;
    case 'artifact.ready':
      upsertArtifact(event);
      break;
    case 'artifact.present':
      presentArtifact(event.artifact_id, { overlay: true });
      break;
    case 'meeting.ended':
      setState(`Ended · ${state.workspaceId || ''}`);
      break;
    case 'workspace.reset':
      reloadSnapshot();
      break;
  }
}

function clearWorkspaceUI() {
  for (const id of ['transcript', 'tasks', 'artifacts', 'stage']) {
    const node = $(id);
    if (node) node.innerHTML = '';
  }
  state.tasks.clear();
  state.artifacts.clear();
  state.utterances = 0;
  $('utterance-count').textContent = '0';
  $('task-count').textContent = '0';
  $('artifact-count').textContent = '0';
  closeOverlay();
}

// A new session reusing the meeting number clears the canvas server-side;
// drop local state and rehydrate from the fresh snapshot.
async function reloadSnapshot() {
  if (!state.server || !state.workspaceId) return;
  clearWorkspaceUI();
  try {
    const snapshot = await (await fetch(
      `${state.server}/api/workspaces/${state.workspaceId}`)).json();
    loadSnapshot(snapshot);
    setState(`Connected · ${state.workspaceId} · new session`);
  } catch (error) {
    fail(`Failed to refresh workspace: ${error.message}`);
  }
}

// Accepts bare host:port (local dev) or a full https:// URL (tunnel/proxy) —
// WS always uses the matching ws/wss scheme so pages served over TLS work.
function serverBases(raw) {
  const secure = /^(https|wss):/i.test(raw);
  const host = String(raw).replace(/^(https?|wss?):\/\//i, '').replace(/\/+$/, '');
  return { http: `${secure ? 'https' : 'http'}://${host}`,
           ws: `${secure ? 'wss' : 'ws'}://${host}` };
}

$('join').onsubmit = async event => {
  event.preventDefault();
  const form = new FormData(event.target);
  const base = serverBases(form.get('server'));
  const kind = 'zoom_uuid', external = form.get('external_id'),
        title = form.get('title') || '';
  state.socket?.close();
  clearWorkspaceUI();
  try {
    const response = await fetch(`${base.http}/api/meetings/resolve?` +
      new URLSearchParams({ kind, external_id: external, title }));
    if (!response.ok) throw new Error(`resolve ${response.status}`);
    const workspace = await response.json();
    state.server = base.http;
    state.workspaceId = workspace.workspace_id;
    $('ws-id').textContent = workspace.workspace_id;
    const snapshot = await (await fetch(`${base.http}/api/workspaces/${workspace.workspace_id}`)).json();
    loadSnapshot(snapshot);
    const socket = new WebSocket(`${base.ws}/workspaces/${workspace.workspace_id}/events`);
    socket.onmessage = ({ data }) => onEvent(JSON.parse(data));
    socket.onopen = () => setState(`Connected · ${workspace.workspace_id}`);
    socket.onclose = () => setState('Disconnected');
    socket.onerror = () => fail('Event stream connection failed — is sparkie workspace running?');
    state.socket = socket;
    $('workspace').hidden = false;
    setState('Connecting…');
  } catch (error) {
    fail(`Cannot reach backend: ${error.message}. Run sparkie workspace first`);
  }
};

$('simulate').onsubmit = event => {
  event.preventDefault();
  const form = new FormData(event.target);
  if (state.socket?.readyState === WebSocket.OPEN) {
    state.socket.send(JSON.stringify({ type: 'utterance', speaker: form.get('speaker'), text: form.get('text') }));
    event.target.text.value = '';
  }
};

$('overlay-return').onclick = closeOverlay;
document.addEventListener?.('keydown', event => {
  if (event.key === 'Escape') closeOverlay();
});



// Shareable entry: /workspace.html?meeting=<zoom id> joins straight in.
try {
  const meeting = new URLSearchParams(globalThis.location?.search || '').get('meeting');
  if (meeting) {
    const form = document.querySelector('#join');
    form.external_id.value = meeting;
    form.requestSubmit();
  }
} catch { /* No location outside the browser. */ }
