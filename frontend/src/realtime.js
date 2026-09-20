import './realtime.css';
import { BrowserVoice } from './browser-voice.js';
let voice = null, starting = false;
const $ = selector => document.querySelector(selector);
let sessionId = null, rendered = 0, busy = false;
const jobs = new Map();
let artifactWorkspace = null;
function renderArtifactBoard(state) {
  const id = state.workspaceId;
  const valid = typeof id === 'string' && /^ws_[a-f0-9]+$/.test(id);
  const frame = $('#artifact-board'), link = $('#artifact-open'), notice = $('#artifact-notice');
  if (valid) {
    const url = `/workspace.html?workspace=${encodeURIComponent(id)}&server=/workspace-api`;
    if (artifactWorkspace !== id) frame.src = `${url}&embedded=1`;
    artifactWorkspace = id;
    link.href = url;
    frame.hidden = link.hidden = false;
    notice.hidden = true;
  } else {
    if (artifactWorkspace) frame.removeAttribute('src');
    artifactWorkspace = null;
    frame.hidden = link.hidden = true;
    notice.hidden = false;
    notice.textContent = !state.id ? '开始对话后，可以让 Sparkie 在这里展示任务成果。'
      : state.status === 'starting' ? '正在连接本轮成果面板…'
      : '成果面板未连接。语音和后台任务仍可使用，结果可在下方任务列表查看。';
  }
}
async function api(route, data) {
  const response = await fetch(`/api/${route}`, data === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '请求失败');
  return result;
}
function error(exc) { $('#error').textContent = exc.message; }
function entry(label, text, gap = false) {
  const feed = $('#conversation'); feed.querySelector('.empty')?.remove();
  const div = document.createElement('div'); div.className = gap ? 'entry gap' : 'entry';
  const title = document.createElement('small'); title.textContent = label;
  const body = document.createElement('p'); body.textContent = text;
  div.append(title, body); feed.append(div); feed.scrollTop = feed.scrollHeight;
}
function renderPartial(text) {
  const feed = $('#conversation');
  let draft = feed.querySelector('.partial');
  if (!text) { draft?.remove(); return; }
  feed.querySelector('.empty')?.remove();
  if (!draft) {
    draft = document.createElement('div'); draft.className = 'entry partial';
    const label = document.createElement('small'); label.textContent = '你 · 正在转写';
    draft.append(label, document.createElement('p'));
  }
  if (draft.querySelector('p').textContent !== text) {
    draft.querySelector('p').textContent = text;
    feed.append(draft); feed.scrollTop = feed.scrollHeight;
  }
}
const statuses = { queued: '等待处理', running: '正在处理', completed: '结果已就绪', failed: '处理失败', cancelled: '已取消' };
function renderJobs() {
  const area = $('#tasks'); area.replaceChildren();
  $('#task-count').textContent = jobs.size;
  for (const job of jobs.values()) {
    const card = document.createElement('article'); card.className = 'task';
    const status = document.createElement('small'); status.textContent =
      `${statuses[job.status] || job.status}${job.backend && job.model ? ` · ${job.backend} / ${job.model}` : ''}`;
    const title = document.createElement('h3'); title.textContent = job.request;
    card.append(status, title);
    if (job.result) { const result = document.createElement('p'); result.textContent = job.result; card.append(result); }
    if (job.artifact_error) { const e = document.createElement('p'); e.textContent = '文档展示失败：' + job.artifact_error; card.append(e); }
    if (job.error_type) { const e = document.createElement('p'); e.textContent = job.error_message || '任务未完成，请查看具体请求后重试。'; card.append(e); }
    if (job.progress && job.status === 'running') {
      const progress = document.createElement('p'); progress.textContent = job.progress; card.append(progress);
    }
    if (['queued', 'running', 'completed'].includes(job.status)) {
      const button = document.createElement('button'); button.className = 'secondary'; button.disabled = !busy;
      button.textContent = job.status === 'completed' ? '播报结果' : '取消任务';
      button.onclick = () => api('control', { action: job.status === 'completed' ? 'report_task' : 'cancel_task', task_id: job.task_id }).catch(error);
      card.append(button);
    }
    area.append(card);
  }
}
function processEvent(event) {
  if (event.type === 'transcript_degraded') entry('连接提示', '转写暂时中断，仍可继续对话。', true);
  if (event.type === 'transcript') entry('你', event.text);
  if (event.type === 'assistant_transcript') entry('Sparkie', event.text);
  if (event.type === 'background_task') { jobs.set(event.task_id, event); renderJobs(); }
  if (event.type === 'control_rejected') $('#error').textContent = event.reason === 'wait_until_speech_finishes' ? '请等当前回复播放结束，再播报结果。' : '任务尚未完成。';
  if (event.type === 'provider_error') $('#error').textContent = `OpenAI 连接错误：${event.code || 'unknown'}`;
}
function renderMute() {
  const muted = Boolean(voice?.muted);
  $('#mute').hidden = !busy;
  $('#mute').disabled = !voice || voice.closed;
  $('#mute').textContent = muted ? '取消静音' : '静音';
  $('#mute').setAttribute('aria-pressed', String(muted));
  if (muted) { $('#notice').textContent = '麦克风已静音'; $('#level').style.width = '0%'; }
}
async function poll() {
  try {
    const state = await api('status');
    if (state.id !== sessionId) {
      sessionId = state.id; rendered = 0; jobs.clear(); $('#conversation').replaceChildren(); $('#tasks').replaceChildren(); $('#task-count').textContent = '0';
    }
    renderArtifactBoard(state);
    const wasBusy = busy;
    busy = ['starting', 'listening', 'stopping'].includes(state.status);
    $('#state').textContent = state.audioStalled && state.status === 'listening' ? '麦克风待恢复'
      : { idle: '准备就绪', starting: '正在连接', listening: '正在聆听', stopping: '正在结束', ended: '已结束', failed: '连接失败' }[state.status] || state.status;
    $('#start').hidden = busy; $('#stop').hidden = !busy; $('#interrupt').hidden = !busy;
    $('#recover').hidden = !busy || !state.audioStalled;
    $('#start').disabled = busy || starting; $('#stop').disabled = !busy || state.status === 'stopping'; $('#interrupt').disabled = state.status !== 'listening';
    $('#setup').querySelectorAll('select').forEach(el => el.disabled = busy);
    $('#level').style.width = `${Math.min(100, (state.level || 0) * 400)}%`;
    if (state.error) $('#error').textContent = state.error;
    if (busy) $('#notice').textContent = state.warning || state.voiceHint ||
      (state.status === 'starting' ? '正在连接…' : state.status === 'stopping' ? '正在结束…' :
        state.speechActive ? (Date.now() - state.speechStartedAt > 8000 ? '正在接收声音，等待你说完' : '听到声音了') :
        state.gated ? '正在回复' : '我在听');
    else if (state.id) $('#notice').textContent = '聊完了，随时继续。';
    renderMute();
    for (const event of state.events) {
      if (event.sequence > rendered) { processEvent(event); rendered = event.sequence; }
    }
    renderPartial(busy ? state.partialTranscript : '');
    if (wasBusy !== busy && jobs.size) renderJobs();
    if (!busy && !starting && voice && state.id === voice.sessionId) { voice.close(); voice = null; }
  } catch (exc) { error(exc); }
  setTimeout(poll, 350);
}
async function devices() {
  const result = await navigator.mediaDevices.enumerateDevices();
  const select = $('[name="inputDevice"]'); const previous = select.value;
  select.replaceChildren(new Option('系统默认', ''));
  for (const device of result.filter(d => d.kind === 'audioinput' && d.deviceId !== 'default')) {
    if (device.deviceId) select.add(new Option(device.label || '麦克风', device.deviceId));
  }
  select.value = [...select.options].some(o => o.value === previous) ? previous : '';
}
$('#setup').onsubmit = async event => {
  event.preventDefault(); if (starting || busy) return;
  starting = true; $('#error').textContent = ''; $('#start').disabled = true;
  const data = Object.fromEntries(new FormData(event.target));
  const inputDevice = data.inputDevice;
  Object.assign(data, { seconds: Number(data.seconds), responseMode: 'realtime', transport: 'browser',
    echoMode: 'headphones', inputDevice: '', outputDevice: '' });
  voice = new BrowserVoice(exc => { error(exc); api('stop', {}).catch(error); });
  try {
    await voice.prepare(inputDevice);
    const state = await api('start', data);
    await voice.connect(state.id);
    busy = true;
    await devices();
  } catch (exc) {
    voice?.close(); voice = null; error(exc); await api('stop', {}).catch(() => {});
  } finally { starting = false; $('#start').disabled = busy; }
};
$('#stop').onclick = () => { voice?.close(); voice = null; api('stop', {}).catch(error); };
$('#recover').onclick = async () => {
  const button = $('#recover'); button.disabled = true;
  try { await voice?.recoverInput(); $('#error').textContent = ''; }
  catch (exc) { error(exc); }
  finally { button.disabled = false; }
};
$('#mute').onclick = () => { voice?.setMuted(!voice.muted); renderMute(); if (!voice?.muted) $('#notice').textContent = '我在听'; };
$('#interrupt').onclick = () => api('control', { action: 'interrupt' }).catch(error);
$('#devices').onclick = () => devices().catch(error);
$('#export').onclick = async () => {
  try {
    const data = await api('transcript');
    const url = URL.createObjectURL(new Blob([data.records.map(r => JSON.stringify(r)).join('\n')], { type: 'application/x-ndjson' }));
    const link = document.createElement('a'); link.href = url; link.download = `sparkie-${sessionId || 'transcript'}.jsonl`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (exc) { error(exc); }
};
api('config').then(config => { if (Object.values(config).some(value => !value)) $('#error').textContent = '服务尚未配置，请先配置 API 密钥。'; }).catch(error);
devices().catch(error);
poll();
