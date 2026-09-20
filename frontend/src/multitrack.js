import './multitrack.css';

const $ = selector => document.querySelector(selector);
const tracks = [];
let context, socket, running = false, recording = null, recordingTimer, recordingPending = false;
let timer, startedAt = 0, frameIndex = 0, totalFrames = 0, sources = [], events = [], result = null;
const RATE = 32000, FRAME = 640;
const setError = message => { $('#error').textContent = message || ''; };
const status = message => { $('#state').textContent = message; };
const seconds = ms => (ms / 1000).toFixed(2) + ' s';
function refresh() {
  $('#start').disabled = running || !!recording || recordingPending || tracks.some(t => !t.samples || t.loading);
  $('#stop').disabled = !running;
  $('#add').disabled = running || !!recording || tracks.length >= 4;
  $('#samples').disabled = running || !!recording;
  $('#language').disabled = running;
  $('#track-count').textContent = tracks.length;
  for (const track of tracks) {
    for (const input of track.card.querySelectorAll('input, button')) input.disabled = running || (!!recording && recording.track !== track);
  }
}
function audioContext() {
  context ||= new AudioContext();
  return context;
}
async function setAudio(track, bytes, label, blob) {
  const version = ++track.version;
  track.loading = true; refresh();
  try {
  const decoded = await audioContext().decodeAudioData(bytes.slice(0));
  if (decoded.duration > 60 || decoded.duration < .05) throw new Error('请选择 0.05–60 秒的音频。');
  const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * RATE), RATE);
  const input = offline.createBufferSource(); input.buffer = decoded; input.connect(offline.destination); input.start();
  const rendered = await offline.startRendering();
  if (track.version !== version) return;
  track.samples = rendered.getChannelData(0).slice(); track.buffer = rendered;
  track.source.textContent = label + ' · ' + rendered.duration.toFixed(2) + ' 秒';
  if (track.url) URL.revokeObjectURL(track.url);
  track.url = URL.createObjectURL(blob); track.audio.src = track.url;
  } finally { if (track.version === version) track.loading = false; refresh(); }
}
function addTrack() {
  const index = tracks.length;
  const card = document.createElement('div'); card.className = 'track';
  card.innerHTML = '<h3></h3><div class="fields"><label>显示名<input class="name" maxlength="80"></label><label>起点（秒）<input class="offset" type="number" value="0" min="0" max="55" step="0.1"></label></div><p class="source">上传音频或录制一段话</p><input class="upload" type="file" accept="audio/*"><audio controls></audio><div class="buttons"><button class="record quiet">录制音轨</button></div>';
  card.querySelector('h3').textContent = '音轨 ' + (index + 1) + ' · zoom:' + (index + 1);
  card.querySelector('.name').value = ['Ava', 'Leo', 'Mia', 'Noah'][index];
  const track = { card, source: card.querySelector('.source'), audio: card.querySelector('audio'), samples: null, version: 0 };
  tracks.push(track); $('#tracks').append(card);
  card.querySelector('.upload').onchange = async event => {
    const file = event.target.files[0]; if (!file) return;
    try {
      if (file.size > 15 * 1024 * 1024) throw new Error('请选择小于 15 MB 的音频文件。');
      setError(); $('#start').disabled = true;
      await setAudio(track, await file.arrayBuffer(), file.name, file);
    } catch (error) { setError(error.message || '无法解码音频，请换一个文件。'); refresh(); }
  };
  card.querySelector('.record').onclick = () => record(track).catch(error => { setError(error.message); refresh(); });
  refresh();
}
async function record(track) {
  if (recording?.track === track) { recording.recorder.stop(); return; }
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('录音需要 localhost 或可信 HTTPS。');
  if (recording || running || recordingPending) return;
  recordingPending = true; refresh();
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true } }); }
  finally { recordingPending = false; refresh(); }
  let recorder;
  try { recorder = new MediaRecorder(stream); }
  catch (error) { stream.getTracks().forEach(t => t.stop()); throw error; }
  const chunks = [];
  recording = { track, recorder, stream };
  const button = track.card.querySelector('.record'); button.textContent = '结束录制'; button.classList.add('recording');
  recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
  recorder.onstop = async () => {
    clearTimeout(recordingTimer); stream.getTracks().forEach(t => t.stop()); recording = null;
    button.textContent = '录制音轨'; button.classList.remove('recording');
    try {
      const blob = new Blob(chunks, { type: recorder.mimeType });
      await setAudio(track, await blob.arrayBuffer(), '本机录音', blob);
    } catch (error) { setError(error.message || '录音处理失败。'); }
    refresh();
  };
  recorder.start(); refresh();
  recordingTimer = setTimeout(() => { if (recorder.state === 'recording') recorder.stop(); }, 55000);
}
async function samples() {
  setError(); $('#start').disabled = true;
  await Promise.all(tracks.slice(0, 2).map(async (track, index) => {
    const response = await fetch('/samples/participant-' + (index + 1) + '.wav');
    if (!response.ok) throw new Error('示例音频加载失败。');
    const blob = await response.blob();
    await setAudio(track, await blob.arrayBuffer(), index ? 'The red apple is on the kitchen table.' : 'The blue bicycle is parked outside the library.', blob);
  }));
  status('示例已就绪。默认同时发言，也可以调整起点。'); refresh();
}
function stopPlayback() {
  clearTimeout(timer);
  for (const source of sources) { try { source.stop(); } catch {} }
  sources = [];
}
function finishUI(message) {
  stopPlayback(); running = false; refresh(); status(message);
  $('#export').disabled = events.length === 0;
}
function stop() {
  const current = socket; socket = null; current?.close();
  if (running) finishUI('已停止。已收到的转写保留，本轮可能不完整。');
}
function pcmPacket(track, frame) {
  const pcm = new Uint8Array(FRAME * 2), view = new DataView(pcm.buffer);
  const offset = frame * FRAME - track.offsetSamples;
  for (let i = 0; i < FRAME; i++) {
    const value = Math.max(-1, Math.min(1, track.samples[offset + i] || 0));
    view.setInt16(i * 2, Math.round(value * (value < 0 ? 32768 : 32767)), true);
  }
  return btoa(String.fromCharCode(...pcm));
}
function pump() {
  if (!running || socket?.readyState !== WebSocket.OPEN) return;
  const elapsed = performance.now() - startedAt;
  if (socket.bufferedAmount > 256 * 1024 || elapsed - frameIndex * 20 > 1500) {
    setError('音频发送积压，已停止本轮。请保持测试页在前台后重试。'); stop(); return;
  }
  const due = Math.min(totalFrames, Math.floor(elapsed / 20) + 1);
  while (frameIndex < due) {
    socket.send(JSON.stringify({ action: 'frame', sequence: frameIndex, tracks: tracks.map(t => pcmPacket(t, frameIndex)) }));
    frameIndex++;
  }
  $('#timeline').textContent = seconds(frameIndex * 20);
  if (frameIndex >= totalFrames) {
    socket.send(JSON.stringify({ action: 'finish' })); status('音频已发送，等待各音轨最终转写…'); return;
  }
  timer = setTimeout(pump, Math.max(1, frameIndex * 20 - (performance.now() - startedAt)));
}
function renderTranscript(event) {
  const container = document.querySelector('[data-speaker="' + event.speaker_id + '"]');
  if (!container) return;
  container.querySelector('.empty')?.remove();
  const line = document.createElement('div'); line.className = 'line';
  const time = document.createElement('small'); time.textContent = '语音时间 ' + seconds(event.timestamp_ms) + ' · 收到于 ' + seconds(event.received_ms);
  const text = document.createElement('p'); text.textContent = event.text;
  line.append(time, text); container.append(line);
  $('#count').textContent = events.filter(e => e.type === 'transcript').length;
}
async function start() {
  if (running || recording || recordingPending || tracks.some(t => t.loading)) return;
  setError();
  for (const track of tracks) {
    if (!track.samples) throw new Error('请为每条音轨提供音频。');
    const offset = Number(track.card.querySelector('.offset').value);
    if (!Number.isFinite(offset) || offset < 0 || offset + track.buffer.duration > 60) throw new Error('音轨起点加时长不能超过 60 秒。');
    if (!track.card.querySelector('.name').value.trim()) throw new Error('请填写参会者显示名。');
    track.offsetSamples = Math.round(offset * RATE);
  }
  await audioContext().resume();
  totalFrames = Math.ceil(Math.max(...tracks.map(t => t.offsetSamples + t.samples.length)) / FRAME);
  events = []; result = null; frameIndex = 0; startedAt = 0; $('#count').textContent = '0'; $('#timeline').textContent = '0.00 s';
  $('#results').replaceChildren();
  tracks.forEach((track, index) => {
    const card = document.createElement('div'); card.className = 'result'; card.dataset.speaker = 'zoom:' + (index + 1);
    const heading = document.createElement('h3'); heading.textContent = track.card.querySelector('.name').value + ' · zoom:' + (index + 1);
    const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = '等待这条音轨的转写…'; card.append(heading, empty); $('#results').append(card);
    track.audio.pause();
  });
  running = true; refresh(); $('#export').disabled = true; $('#result-mode').textContent = '真实 Deepgram · 模拟参会者输入'; status('正在连接转写服务…');
  const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/multitrack-audio'); socket = ws;
  ws.onopen = () => ws.send(JSON.stringify({ action: 'start', language: $('#language').value,
    tracks: tracks.map(t => ({ name: t.card.querySelector('.name').value.trim() })) }));
  ws.onmessage = ({ data }) => {
    if (socket !== ws) return;
    const event = JSON.parse(data); event.received_ms = startedAt ? Math.round(performance.now() - startedAt) : 0;
    events.push(event);
    if (event.type === 'ready') {
      startedAt = performance.now(); status('正在同时发送各音轨…');
      if ($('#monitor').checked) {
        tracks.forEach(track => {
          const source = audioContext().createBufferSource(); source.buffer = track.buffer;
          const gain = audioContext().createGain(); gain.gain.value = 1 / tracks.length;
          source.connect(gain).connect(context.destination); source.start(context.currentTime + track.offsetSamples / RATE); sources.push(source);
        });
      }
      pump();
    } else if (event.type === 'transcript') renderTranscript(event);
    else if (event.type === 'completed') { result = event; finishUI('本轮转写完成。可调整重叠时间或更换音轨再次测试。'); }
    else if (event.type === 'failed') {
      setError(event.reason === 'missing_deepgram_key' ? '服务端缺少 DEEPGRAM_API_KEY。' : '本轮转写失败，请检查网络、Deepgram 配置或输入音频。');
      finishUI('测试失败，已收到的转写保留。');
    }
  };
  ws.onerror = () => { if (socket === ws) { setError('连接失败；可能已有另一轮多音轨测试正在运行。'); finishUI('连接失败'); } };
  ws.onclose = () => { if (socket === ws) { socket = null; if (running) finishUI('连接已结束，本轮未完整完成。'); } };
}
$('#start').onclick = () => start().catch(error => { setError(error.message); if (running) stop(); });
$('#stop').onclick = stop;
$('#add').onclick = addTrack;
$('#samples').onclick = () => samples().catch(error => { setError(error.message); refresh(); });
$('#export').onclick = () => {
  const blob = new Blob([JSON.stringify({ mode: 'deepgram', simulated_input: true, result, events }, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob), link = document.createElement('a'); link.href = url; link.download = 'sparkie-multitrack.json'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
window.addEventListener('pagehide', () => { stop(); recording?.stream.getTracks().forEach(t => t.stop()); clearTimeout(recordingTimer); context?.close(); });
addTrack(); addTrack(); samples().catch(error => { setError(error.message); status('可上传音频或录制后测试。'); refresh(); });
