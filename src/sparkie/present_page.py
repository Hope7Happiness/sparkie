"""Self-contained presentation page served by the workspace server.

GET /workspaces/<id>/present renders the stage view — the surface Sparkie
shares into the meeting via app-window screen share. It subscribes to the
same broadcast socket as the full workspace UI, hydrates presented artifacts
and renders markdown/image/pdf/url content. No build step or vite server
required, so the native receiver can point a WebView at the backend directly.
"""


def present_html(workspace_id):
    return TEMPLATE.replace("__WS_ID__", workspace_id)


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sparkie</title>
<style>
*{box-sizing:border-box;margin:0}
body{font-family:Inter,-apple-system,"Segoe UI",sans-serif;background:#f7f6f1;color:#29352e;min-height:100vh;display:flex;flex-direction:column}
.bar{display:flex;align-items:center;gap:10px;padding:14px 22px;border-bottom:1px solid #e2e5db;font-size:13px;color:#69756b}
.brand{font-weight:700;font-size:15px;color:#29352e}
.brand span{color:#bb5c3d}
.badge{margin-left:auto;font-size:11px;padding:3px 9px;border-radius:999px;background:#eceee5;border:1px solid #dfe2d6}
.badge.live{background:#dfe9d8;border-color:#c9d9bd;color:#3f5a35}
main{flex:1;overflow:auto;padding:34px 46px}
.empty{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#8a948a;gap:10px}
.empty .big{font-size:44px}
.empty p{font-size:15px}
.art-head{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:22px}
.art-head h1{font-size:26px;letter-spacing:-.4px}
.art-head .type{font-size:11px;padding:3px 9px;border-radius:999px;background:#29352e;color:#fff}
.art-head .sum{flex-basis:100%;color:#69756b;font-size:14px;margin-top:4px}
.body{font-size:15.5px;line-height:1.65;max-width:980px}
.body h1,.body h2,.body h3{margin:26px 0 10px;letter-spacing:-.3px}
.body h1{font-size:22px}.body h2{font-size:19px}.body h3{font-size:16px}
.body p{margin:10px 0}
.body ul,.body ol{margin:10px 0 10px 24px}
.body li{margin:4px 0}
.body table{border-collapse:collapse;margin:14px 0;font-size:14px;width:100%}
.body th,.body td{border:1px solid #d8dcd0;padding:7px 11px;text-align:left;vertical-align:top}
.body th{background:#eceee5}
.body code{background:#eceee5;border-radius:4px;padding:1px 5px;font-size:13px}
.body pre{background:#29352e;color:#e8eae2;border-radius:8px;padding:14px 16px;overflow:auto;margin:12px 0}
.body pre code{background:none;padding:0;color:inherit}
.body blockquote{border-left:3px solid #c9d0be;padding-left:14px;color:#69756b;margin:12px 0}
.body hr{border:none;border-top:1px solid #dfe2d6;margin:20px 0}
.body img{max-width:100%;border-radius:8px}
.body iframe{width:100%;height:72vh;border:1px solid #dfe2d6;border-radius:8px;background:#fff}
</style>
</head>
<body>
<div class="bar"><div class="brand"><span>✳</span> sparkie</div><span id="meeting"></span><span id="status" class="badge">connecting…</span></div>
<main id="stage"><div class="empty"><div class="big">✳</div><p>Waiting for artifacts…</p></div></main>
<script>
const WS_ID = "__WS_ID__";
const httpBase = location.origin;
const wsUrl = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host +
  '/workspaces/' + WS_ID + '/events';
const stage = document.getElementById('stage');
const statusEl = document.getElementById('status');
const meetingEl = document.getElementById('meeting');
let active = null;

const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const inline = s => esc(s)
  .replace(/`([^`]+)`/g, '<code>$1</code>')
  .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
  .replace(/\\*([^*]+)\\*/g, '<em>$1</em>')
  .replace(/\\[([^\\]]+)\\]\\((https?:[^\\s)]+)\\)/g, '<a href="$2" target="_blank">$1</a>');

function markdown(src) {
  const lines = String(src).split('\\n');
  let html = '', i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\\s*```/.test(line)) {
      let buf = [];
      for (i++; i < lines.length && !/^\\s*```/.test(lines[i]); i++) buf.push(lines[i]);
      i++;
      html += '<pre><code>' + esc(buf.join('\\n')) + '</code></pre>';
      continue;
    }
    if (/^\\s*#{1,6}\\s/.test(line)) {
      const level = Math.min(line.match(/^\\s*(#+)/)[1].length, 3);
      html += '<h' + level + '>' + inline(line.replace(/^\\s*#+\\s*/, '')) + '</h' + level + '>';
      i++; continue;
    }
    if (/^\\s*\\|.*\\|\\s*$/.test(line) && i + 1 < lines.length && /^\\s*\\|[\\s:\\-|]+\\|\\s*$/.test(lines[i + 1])) {
      const rows = [];
      const head = line;
      i += 2;
      while (i < lines.length && /^\\s*\\|/.test(lines[i])) { rows.push(lines[i]); i++; }
      const cells = r => r.replace(/^\\s*\\||\\|\\s*$/g, '').split('|').map(c => inline(c.trim()));
      html += '<table><thead><tr>' + cells(head).map(c => '<th>' + c + '</th>').join('') + '</tr></thead><tbody>' +
        rows.map(r => '<tr>' + cells(r).map(c => '<td>' + c + '</td>').join('') + '</tr>').join('') + '</tbody></table>';
      continue;
    }
    if (/^\\s*([-*+]\\s|\\d+\\.\\s)/.test(line)) {
      const ordered = /^\\s*\\d+\\./.test(line);
      const tag = ordered ? 'ol' : 'ul';
      let items = '';
      while (i < lines.length && /^\\s*([-*+]\\s|\\d+\\.\\s)/.test(lines[i])) {
        items += '<li>' + inline(lines[i].replace(/^\\s*(?:[-*+]|\\d+\\.)\\s*/, '')) + '</li>'; i++;
      }
      html += '<' + tag + '>' + items + '</' + tag + '>';
      continue;
    }
    if (/^\\s*>/.test(line)) { html += '<blockquote>' + inline(line.replace(/^\\s*>\\s?/, '')) + '</blockquote>'; i++; continue; }
    if (/^\\s*---+\\s*$/.test(line)) { html += '<hr>'; i++; continue; }
    if (!line.trim()) { i++; continue; }
    let para = line;
    for (i++; i < lines.length && lines[i].trim() && !/^\\s*(#{1,6}\\s|[-*+]\\s|\\d+\\.\\s|>|```|\\|)/.test(lines[i]); i++) para += ' ' + lines[i];
    html += '<p>' + inline(para) + '</p>';
  }
  return html;
}

function render(artifact) {
  const c = artifact.content || {};
  const head = '<div class="art-head"><h1>' + esc(artifact.title || 'Artifact') + '</h1>' +
    '<span class="type">' + esc(artifact.type || 'report') + '</span>' +
    (artifact.summary ? '<p class="sum">' + esc(artifact.summary) + '</p>' : '') + '</div>';
  let body = '';
  if (c.markdown) body = '<div class="body">' + markdown(c.markdown) + '</div>';
  else if (c.image) body = '<div class="body"><img src="' + esc(c.image) + '"></div>';
  else if (c.pdf) body = '<div class="body"><iframe src="' + esc(c.pdf) + '"></iframe></div>';
  else if (c.url) body = '<div class="body"><iframe src="' + esc(c.url) + '"></iframe></div>';
  else body = '<div class="body"><pre><code>' + esc(JSON.stringify(c, null, 2)) + '</code></pre></div>';
  stage.innerHTML = head + body;
}

async function hydrate(id) {
  const res = await fetch(httpBase + '/api/artifacts/' + id);
  if (!res.ok) return null;
  return res.json();
}

async function present(id) {
  const artifact = await hydrate(id);
  if (artifact) { active = id; render(artifact); }
}

function connect() {
  const socket = new WebSocket(wsUrl);
  socket.onopen = () => { statusEl.textContent = 'live'; statusEl.className = 'badge live'; };
  socket.onclose = () => { statusEl.textContent = 'reconnecting…'; statusEl.className = 'badge'; setTimeout(connect, 2000); };
  socket.onmessage = e => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    if (msg.type === 'artifact.present' && msg.artifact_id) present(msg.artifact_id);
    else if (msg.type === 'artifact.ready' && !active && msg.artifact_id) present(msg.artifact_id);
    else if (msg.type === 'workspace.reset') location.reload();
  };
}

fetch(httpBase + '/api/workspaces/' + WS_ID).then(r => r.json()).then(snap => {
  meetingEl.textContent = snap.title || WS_ID;
  const activeId = (snap.meeting_state || {}).active_artifact_id;
  if (activeId) present(activeId);
  else if (snap.artifacts && snap.artifacts.length) present(snap.artifacts[snap.artifacts.length - 1].artifact_id);
}).catch(() => {});
connect();
</script>
</body>
</html>
"""
