import './style.css';
import { deriveTrials } from './trials.js';
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
function trials() { return deriveTrials(state); }
function trialStatus(trial) {
  if (!trial.answerRequested) return trial.stage === 'completed' ? '仅唤醒' : trial.stage === 'cancelled' ? '已取消' : trial.stage === 'failed' ? '确认失败' : '正在确认';
  return { acknowledgement: '正在确认', thinking: '思考中', synthesis: '准备语音', speaking: '朗读中', completed: '已回答', failed: '回答失败', cancelled: '已取消' }[trial.stage] || '等待回答';
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
  const records = trials();
  const latest = records.at(-1);
  const qa = (state.id ? state.options?.responseMode : $('mode').value) === 'qa';
  const working = latest?.answerRequested && !['completed', 'failed', 'cancelled'].includes(latest.stage);
  $('connection').textContent = online ? '本地服务已连接' : '本地服务连接中断';
  $('start').hidden = running;
  $('stop').hidden = !running;
  $('start').disabled = busy || !online;
  $('stop').disabled = busy || state.status === 'stopping' || !online;
  for (const id of ['mode', 'input', 'output', 'language', 'echo', 'seconds']) $(id).disabled = running || busy;
  const labels = { idle: '准备就绪', starting: '连接中', listening: '正在聆听', stopping: '正在停止', ended: '测试结束', failed: '测试失败' };
  $('status').textContent = online ? state.status === 'listening' && working ? trialStatus(latest) : labels[state.status] || state.status : '服务离线';
  $('status').classList.toggle('active', running);
  $('stage').classList.toggle('live', state.status === 'listening' && online);
  const descriptions = {
    idle: ['准备好就开口', qa ? '说 “Sparkie” 后紧接问题，整句说完再停顿' : '点击开始，等待连接后说 “Sparkie”'],
    starting: ['正在连接声音', '准备回复语音并连接 Deepgram，请稍候'],
    listening: state.gated ? ['Sparkie 正在回应', '扬声器播放期间暂停识别，等回复结束后再说'] : working ? ['Sparkie ' + trialStatus(latest), '你可以继续说话补充上下文；下一题请等当前回答结束'] : ['我在听，说 “Sparkie”', qa ? '紧接着说出问题，或问问刚才聊了什么' : '说完后停顿，等待 “I’m here.”'],
    stopping: ['正在结束测试', '停止采集并保存本轮记录'],
    ended: ['这一轮，完成了', '查看下方记录，或再开始一轮测试'],
    failed: ['这一轮已中断', '查看下方原因，重新开始后再叫醒 Sparkie'],
  };
  [$('prompt').textContent, $('hint').textContent] = online ? descriptions[state.status] || descriptions.idle : ['本地服务已断开', '请重启 bash scripts/web.sh；无页面心跳 15 秒后停止采集'];
  $('mic-note').textContent = !online ? '无法获取麦克风状态' : state.status === 'listening' ? state.gated ? '回声保护 · 识别暂停' : '实时输入电平' : '麦克风未在聆听';
  const level = running && online ? Math.min(1, Math.sqrt(state.level || 0) * 2) : 0;
  bars.forEach((bar, i) => { bar.style.height = `${3 + level * 32 * (.3 + .7 * Math.abs(Math.sin(i * 1.9 + (state.level || 0) * 20))) * Math.sin((i + 1) / 50 * Math.PI)}px`; });
  const end = running ? Date.now() - (state.startedAt || Date.now()) : state.events.at(-1)?.elapsed_ms || 0;
  $('elapsed').textContent = time(end);
  $('warning').textContent = state.warning || '';
  $('warning').hidden = !state.warning || !!state.error;
  if (state.error) error(state.error);
  $('download').disabled = !state.id;
  const signature = `${state.id}:${state.events.length}:${state.timingReliable}:${state.status}:${qa}`;
  if (signature === viewSignature) return;
  viewSignature = signature;
  const valid = records.filter(t => t.valid);
  $('latency-title').textContent = qa ? '最近一次答案' : '最近一次确认';
  $('playback-label').textContent = qa ? '识别唤醒 → 实际回答' : '识别唤醒 → 确认回应';
  $('answer-metrics').hidden = !qa;
  $('answer-note').hidden = !qa;
  const config = state.events.find(e => e.type === 'reasoning_config');
  $('reasoning-model').textContent = config ? `${config.model}${config.reasoning_effort ? ' · ' + config.reasoning_effort : ''}` : '本轮模型连接后显示';
  $('stats-label').textContent = qa ? '答案样本' : '确认样本';
  $('ack-time').textContent = latest?.ackValid ? ms(latest.ackTotal) : '—';
  $('text-time').textContent = ms(latest?.textTotal);
  $('complete-time').textContent = ms(latest?.answerCompleted);
  $('total').textContent = latest?.valid ? Math.round(latest.total).toLocaleString() : '—';
  $('recognition').textContent = latest?.ackValid ? ms(latest.recognition) : '—';
  $('playback').textContent = latest?.valid ? ms(latest.playback) : '—';
  $('metric-caption').textContent = !state.timingReliable && records.length ? '音频出现丢帧或欠载 · 本轮计时无效' : latest && !latest.valid ? trialStatus(latest) + (qa && !latest.answerRequested ? ' · 请在 Sparkie 后紧接问题' : '') : qa ? '说完问题 → 开始朗读答案' : '说完最后一个词 → 开始确认回应';
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
      [String(records.length - i).padStart(2, '0'), trial.text,
        trial.ackValid ? ms(trial.ackTotal) : trial.invalid || !state.timingReliable ? '计时无效' : '—',
        trial.answerValid ? ms(trial.answerTotal) : trial.invalid || !state.timingReliable ? '计时无效' : '—',
        trialStatus(trial)].forEach(text => addText(row, 'td', text));
      table.append(row);
    });
  } else {
    table.replaceChildren();
    const row = document.createElement('tr');
    const cell = addText(row, 'td', '开始测试后，每一次唤醒都会记录在这里。', 'table-empty'); cell.colSpan = 5; table.append(row);
  }
  const messages = state.events.filter(e => ['transcript', 'reply', 'answer', 'response_failed', 'response_cancelled'].includes(e.type) || (e.type === 'ignored' && e.reason === 'response_busy'));
  const transcript = $('transcripts');
  if (messages.length) {
    const atBottom = transcript.scrollTop + transcript.clientHeight >= transcript.scrollHeight - 35;
    transcript.replaceChildren();
    for (const event of messages) {
      const isHuman = event.type === 'transcript';
      const notice = ['response_failed', 'response_cancelled', 'ignored'].includes(event.type);
      const bubble = addText(transcript, 'div', '', `bubble ${isHuman ? '' : 'bot'} ${event.type === 'answer' ? 'answer' : ''} ${notice ? 'notice' : ''}`);
      const label = { transcript: '你 · 最终转录', reply: 'SPARKIE · 确认回应', answer: 'SPARKIE · 回答', response_failed: 'SPARKIE · 未完成', response_cancelled: 'SPARKIE · 已取消', ignored: 'SPARKIE · 正忙' }[event.type];
      const notAwakened = isHuman && state.events.some(e => e.type === 'ignored' && e.reason === 'not_addressed_request' && e.event_id === event.event_id);
      const speaker = addText(bubble, 'div', notAwakened ? '你 · 已记入上下文，未触发唤醒' : label, 'speaker');
      addText(speaker, 'span', time(event.elapsed_ms));
      const failure = event.phase === 'reasoning' ? '答案生成失败，请检查推理服务后重新提问。' : event.phase === 'answer_synthesis' ? '答案文字已保留，语音生成失败。请检查 Deepgram 配置或网络。' : '音频播放失败，请检查输出设备后重试。';
      addText(bubble, 'p', event.type === 'response_failed' ? failure : event.type === 'response_cancelled' ? '本次回答已取消。' : event.type === 'ignored' ? '当前回答尚未结束，请稍后重新叫醒并提问。' : event.text);
    }
    if (atBottom) transcript.scrollTop = transcript.scrollHeight;
  } else {
    transcript.replaceChildren();
    const empty = addText(transcript, 'div', '', 'empty');
    addText(empty, 'span', '“ ”'); addText(empty, 'p', '你的声音会出现在这里'); addText(empty, 'small', '试试 “Sparkie, what is a WebSocket?”，然后停顿。');
  }
  $('events').textContent = state.id ? `会话 ${state.id}\n${state.events.map(e => JSON.stringify(e)).join('\n')}` : '尚无会话';
}
$('start').addEventListener('click', async () => {
  busy = true; error(''); render();
  try {
    state = await api('start', { responseMode: $('mode').value, language: $('language').value, echoMode: $('echo').value, seconds: Number($('seconds').value), inputDevice: $('input').value === '' ? '' : Number($('input').value), outputDevice: $('output').value === '' ? '' : Number($('output').value) });
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
$('mode').addEventListener('change', render);
devices(); poll();
