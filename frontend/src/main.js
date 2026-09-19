import './style.css';
const $ = id => document.getElementById(id);
let state = { status: 'idle', events: [] };
let online = false, busy = false, viewSignature = '';
const bars = Array.from({ length: 49 }, (_, i) => {
  const bar = document.createElement('i');
  $('wave').append(bar);
  return bar;
});
const active = () => ['starting', 'listening', 'stopping'].includes(state.status);
const ms = value => Number.isFinite(value) && value >= 0 ? `${Math.round(value).toLocaleString()} ms` : '—';
const time = value => `${String(Math.floor(value / 60000)).padStart(2, '0')}:${String(Math.floor(value / 1000) % 60).padStart(2, '0')}`;
function error(message) { $('error').textContent = message || ''; $('error').hidden = !message; }
async function api(route, data) {
  const response = await fetch(`/api/${route}`, { ...(data ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) } : {}), signal: AbortSignal.timeout(12000) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '本地服务暂时不可用');
  return result;
}
function trials() {
  const list = [];
  for (const event of state.events) {
    if (event.type === 'wake') list.push({ text: state.events.find(e => e.type === 'transcript' && e.event_id === event.event_id)?.text || 'Sparkie', at: event.elapsed_ms });
    const trial = list.at(-1);
    if (!trial) continue;
    if (event.type === 'playback_timing') Object.assign(trial, { total: event.utterance_end_to_dac_estimate_ms, playback: event.detection_to_dac_estimate_ms });
    if (event.type === 'playback_timing_unavailable') trial.invalid = true;
    if (event.type === 'response_failed' || event.type === 'response_cancelled') trial.failed = true;
  }
  for (const trial of list) {
    if (['ended', 'failed'].includes(state.status) && !Number.isFinite(trial.total)) trial.failed = true;
    trial.recognition = trial.total - trial.playback;
    trial.valid = state.timingReliable && !trial.invalid && !trial.failed && Number.isFinite(trial.total) && trial.total >= 0 && trial.recognition >= 0;
  }
  return list;
}
function addText(parent, tag, text, className) {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  parent.append(node);
  return node;
}
function render() {
  const running = active();
  $('connection').textContent = online ? '本地服务已连接' : '本地服务连接中断';
  $('start').hidden = running;
  $('stop').hidden = !running;
  $('start').disabled = busy || !online;
  $('stop').disabled = busy || state.status === 'stopping' || !online;
  for (const id of ['input', 'output', 'language', 'echo', 'seconds']) $(id).disabled = running || busy;
  const labels = { idle: '准备就绪', starting: '连接中', listening: '正在聆听', stopping: '正在停止', ended: '测试结束', failed: '测试失败' };
  $('status').textContent = online ? labels[state.status] || state.status : '服务离线';
  $('status').classList.toggle('active', running);
  $('stage').classList.toggle('live', state.status === 'listening' && online);
  const descriptions = {
    idle: ['准备好就开口', '点击开始，等待连接后说 “Sparkie”'],
    starting: ['正在连接声音', '准备回复语音并连接 Deepgram，请稍候'],
    listening: state.gated ? ['Sparkie 正在回应', '回复结束后，再试着叫醒一次'] : ['我在听，说 “Sparkie”', '说完后停顿，等待 “I’m here.”'],
    stopping: ['正在结束测试', '停止采集并保存本轮记录'],
    ended: ['这一轮，完成了', '查看下方记录，或再开始一轮测试'],
    failed: ['连接遇到了一点问题', '检查设备、网络与系统麦克风权限后重试'],
  };
  [$('prompt').textContent, $('hint').textContent] = online ? descriptions[state.status] || descriptions.idle : ['本地服务已断开', '请重启 bash scripts/web.sh；无页面心跳 15 秒后停止采集'];
  $('mic-note').textContent = !online ? '无法获取麦克风状态' : state.status === 'listening' ? state.gated ? '回声保护 · 识别暂停' : '实时输入电平' : '麦克风未在聆听';
  const level = running && online ? Math.min(1, Math.sqrt(state.level || 0) * 2) : 0;
  bars.forEach((bar, i) => { bar.style.height = `${3 + level * 32 * (.3 + .7 * Math.abs(Math.sin(i * 1.9 + (state.level || 0) * 20))) * Math.sin((i + 1) / 50 * Math.PI)}px`; });
  const end = running ? Date.now() - (state.startedAt || Date.now()) : state.events.at(-1)?.elapsed_ms || 0;
  $('elapsed').textContent = time(end);
  if (state.error) error(state.error);
  $('download').disabled = !state.id;
  const signature = `${state.id}:${state.events.length}:${state.timingReliable}:${state.status}`;
  if (signature === viewSignature) return;
  viewSignature = signature;
  const records = trials();
  const latest = records.at(-1);
  const valid = records.filter(t => t.valid);
  $('total').textContent = latest?.valid ? Math.round(latest.total).toLocaleString() : '—';
  $('recognition').textContent = latest?.valid ? ms(latest.recognition) : '—';
  $('playback').textContent = latest?.valid ? ms(latest.playback) : '—';
  $('metric-caption').textContent = !state.timingReliable && records.length ? '音频出现丢帧或欠载 · 本轮计时无效' : latest?.failed ? '回复失败或取消 · 无有效延迟' : latest && !latest.valid ? '等待回复完成后生成计时' : '说完最后一个词 → 开始播放回复';
  $('recognition-bar').style.width = latest?.valid && latest.total ? `${latest.recognition / latest.total * 100}%` : '0';
  $('playback-bar').style.width = latest?.valid && latest.total ? `${latest.playback / latest.total * 100}%` : '0';
  $('count').textContent = `${records.length} 次唤醒`;
  $('samples').textContent = valid.length;
  $('average').textContent = valid.length ? ms(valid.reduce((n, t) => n + t.total, 0) / valid.length) : '—';
  $('fastest').textContent = valid.length ? ms(Math.min(...valid.map(t => t.total))) : '—';
  $('slowest').textContent = valid.length ? ms(Math.max(...valid.map(t => t.total))) : '—';
  const table = $('trials');
  if (records.length) {
    table.replaceChildren();
    records.toReversed().forEach((trial, i) => {
      const row = document.createElement('tr');
      [String(records.length - i).padStart(2, '0'), trial.text, trial.valid ? ms(trial.recognition) : '—', trial.valid ? ms(trial.playback) : '—', trial.valid ? ms(trial.total) : trial.failed ? '未完成' : !state.timingReliable || trial.invalid ? '计时无效' : '等待回复'].forEach(text => addText(row, 'td', text));
      table.append(row);
    });
  } else {
    table.replaceChildren();
    const row = document.createElement('tr');
    const cell = addText(row, 'td', '开始测试后，每一次唤醒都会记录在这里。', 'table-empty'); cell.colSpan = 5; table.append(row);
  }
  const messages = state.events.filter(e => ['transcript', 'reply'].includes(e.type));
  const transcript = $('transcripts');
  if (messages.length) {
    const atBottom = transcript.scrollTop + transcript.clientHeight >= transcript.scrollHeight - 35;
    transcript.replaceChildren();
    for (const event of messages) {
      const bubble = addText(transcript, 'div', '', `bubble ${event.type === 'reply' ? 'bot' : ''}`);
      const speaker = addText(bubble, 'div', event.type === 'reply' ? 'SPARKIE · 回复请求' : '你 · 最终转录', 'speaker');
      addText(speaker, 'span', time(event.elapsed_ms));
      addText(bubble, 'p', event.text);
    }
    if (atBottom) transcript.scrollTop = transcript.scrollHeight;
  } else {
    transcript.replaceChildren();
    const empty = addText(transcript, 'div', '', 'empty');
    addText(empty, 'span', '“ ”'); addText(empty, 'p', '你的声音会出现在这里'); addText(empty, 'small', '试试 “Sparkie, are you there?”，然后停顿。');
  }
  $('events').textContent = state.id ? `会话 ${state.id}\n${state.events.map(e => JSON.stringify(e)).join('\n')}` : '尚无会话';
}
$('start').addEventListener('click', async () => {
  busy = true; error(''); render();
  try {
    state = await api('start', { language: $('language').value, echoMode: $('echo').value, seconds: Number($('seconds').value), inputDevice: $('input').value === '' ? '' : Number($('input').value), outputDevice: $('output').value === '' ? '' : Number($('output').value) });
  } catch (e) { error(e.message); }
  finally { busy = false; render(); }
});
$('stop').addEventListener('click', async () => {
  busy = true; render();
  try { state = await api('stop', {}); } catch (e) { error(e.message); }
  finally { busy = false; render(); }
});
$('download').addEventListener('click', () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify({ ...state, trials: trials(), note: 'Device timestamp estimates, not independently measured acoustic latency.' }, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = url; link.download = `sparkie-${state.id}.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
async function poll() {
  try { if (!busy) { state = await api('status'); online = true; } }
  catch { online = false; }
  render(); setTimeout(poll, 250);
}
async function devices() {
  try {
    const result = await api('devices');
    for (const kind of ['input', 'output']) for (const device of result.devices.filter(d => d[kind])) {
      const option = new Option(device.name, String(device.id)); $(kind).add(option);
    }
  } catch (e) { error(e.message); }
}
devices(); poll();
