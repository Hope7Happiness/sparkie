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
    notice.textContent = !state.id ? 'Start a conversation and ask Sparkie to present task results here.'
      : state.status === 'starting' ? 'Connecting the artifact board…'
      : 'The artifact board is unavailable. Voice and background tasks still work; results appear in the task list below.';
  }
}
async function api(route, data) {
  const response = await fetch(`/api/${route}`, data === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed');
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
    const label = document.createElement('small'); label.textContent = 'You · Transcribing';
    draft.append(label, document.createElement('p'));
  }
  if (draft.querySelector('p').textContent !== text) {
    draft.querySelector('p').textContent = text;
    feed.append(draft); feed.scrollTop = feed.scrollHeight;
  }
}
const statuses = { queued: 'Queued', running: 'Running', completed: 'Ready', failed: 'Failed', cancelled: 'Cancelled' };
function renderJobs() {
  const area = $('#tasks'); area.replaceChildren();
  $('#task-count').textContent = jobs.size;
  for (const job of jobs.values()) {
    const card = document.createElement('article'); card.className = 'task';
    const status = document.createElement('small'); status.textContent =
      `${statuses[job.status] || job.status}${job.backend && job.model ? ` · ${job.backend} / ${job.model}` : ''}`;
    const title = document.createElement('h3'); title.textContent = job.artifact_title || 'Task output';
    card.append(status, title);
    if (job.result) { const result = document.createElement('p'); result.textContent = job.result; card.append(result); }
    if (job.artifact_error) { const e = document.createElement('p'); e.textContent = 'Artifact preview failed: ' + job.artifact_error; card.append(e); }
    if (job.error_type) { const e = document.createElement('p'); e.textContent = job.error_message || 'The task did not complete. Review the request and try again.'; card.append(e); }
    if (job.progress && job.status === 'running') {
      const progress = document.createElement('p'); progress.textContent = job.progress; card.append(progress);
    }
    if (['queued', 'running', 'completed'].includes(job.status)) {
      const button = document.createElement('button'); button.className = 'secondary'; button.disabled = !busy;
      button.textContent = job.status === 'completed' ? 'Announce result' : 'Cancel task';
      button.onclick = () => api('control', { action: job.status === 'completed' ? 'report_task' : 'cancel_task', task_id: job.task_id }).catch(error);
      card.append(button);
    }
    area.append(card);
  }
}
function processEvent(event) {
  if (event.type === 'transcript_degraded') entry('Connection notice', 'Transcription is temporarily unavailable. You can continue the conversation.', true);
  if (event.type === 'transcript') entry('You', event.text);
  if (event.type === 'assistant_transcript') entry('Sparkie', event.text);
  if (event.type === 'background_task') { jobs.set(event.task_id, event); renderJobs(); }
  if (event.type === 'control_rejected') $('#error').textContent = event.reason === 'wait_until_speech_finishes' ? 'Wait for the current reply to finish before announcing the result.' : 'The task is not complete yet.';
  if (event.type === 'provider_error') $('#error').textContent = `OpenAI connection error: ${event.code || 'unknown'}`;
}
function renderMute() {
  const muted = Boolean(voice?.muted);
  $('#mute').hidden = !busy;
  $('#mute').disabled = !voice || voice.closed;
  $('#mute').textContent = muted ? 'Unmute' : 'Mute';
  $('#mute').setAttribute('aria-pressed', String(muted));
  if (muted) { $('#notice').textContent = 'Microphone muted'; $('#level').style.width = '0%'; }
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
    $('#state').textContent = state.audioStalled && state.status === 'listening' ? 'Microphone recovery needed'
      : { idle: 'Ready', starting: 'Connecting', listening: 'Listening', stopping: 'Stopping', ended: 'Ended', failed: 'Connection failed' }[state.status] || state.status;
    $('#start').hidden = busy; $('#stop').hidden = !busy; $('#interrupt').hidden = !busy;
    $('#recover').hidden = !busy || !state.audioStalled;
    $('#start').disabled = busy || starting; $('#stop').disabled = !busy || state.status === 'stopping'; $('#interrupt').disabled = state.status !== 'listening';
    $('#setup').querySelectorAll('select').forEach(el => el.disabled = busy);
    $('#level').style.width = `${Math.min(100, (state.level || 0) * 400)}%`;
    if (state.error) $('#error').textContent = state.error;
    if (busy) $('#notice').textContent = state.warning || state.voiceHint ||
      (state.status === 'starting' ? 'Connecting…' : state.status === 'stopping' ? 'Stopping…' :
        state.speechActive ? (Date.now() - state.speechStartedAt > 8000 ? 'Receiving audio; waiting for you to finish' : 'Speech detected') :
        state.gated ? 'Replying' : 'Listening');
    else if (state.id) $('#notice').textContent = 'Conversation ended. Start again anytime.';
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
  select.replaceChildren(new Option('System default', ''));
  for (const device of result.filter(d => d.kind === 'audioinput' && d.deviceId !== 'default')) {
    if (device.deviceId) select.add(new Option(device.label || 'Microphone', device.deviceId));
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
$('#mute').onclick = () => { voice?.setMuted(!voice.muted); renderMute(); if (!voice?.muted) $('#notice').textContent = 'Listening'; };
$('#interrupt').onclick = () => api('control', { action: 'interrupt' }).catch(error);
$('#devices').onclick = () => devices().catch(error);
$('#export').onclick = async () => {
  try {
    const data = await api('transcript');
    const url = URL.createObjectURL(new Blob([data.records.map(r => JSON.stringify(r)).join('\n')], { type: 'application/x-ndjson' }));
    const link = document.createElement('a'); link.href = url; link.download = `sparkie-${sessionId || 'transcript'}.jsonl`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (exc) { error(exc); }
};
api('config').then(config => { if (Object.values(config).some(value => !value)) $('#error').textContent = 'Configure the API keys before starting a session.'; }).catch(error);
devices().catch(error);
poll();
