import './multitrack.css';

const $ = selector => document.querySelector(selector);
const silence = btoa('\0'.repeat(1280));
let current = null, events = [], result = null;
const names = () => [0, 1].map(i => $('#speaker-' + i).value.trim());
const setError = message => { $('#error').textContent = message || ''; };
const status = message => { $('#state').textContent = message; };
function clock(ms) {
  const seconds = Math.floor(ms / 1000);
  return String(Math.floor(seconds / 60)).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
}
function render() {
  const active = current?.phase === 'listening';
  const busy = !!current;
  $('#start').hidden = busy; $('#stop').hidden = !busy;
  $('#stop').disabled = current?.phase === 'finishing';
  $('#timeline').hidden = !busy && !events.length;
  $('.settings-drawer').querySelectorAll('input,select,button').forEach(el => { el.disabled = busy; });
  [0, 1].forEach(i => {
    const selected = active && current.speaker === i, name = names()[i] || ('Speaker ' + (i + 1));
    $('#name-' + i).textContent = name; $('#transcript-name-' + i).textContent = name;
    $('#mic-' + i).setAttribute('aria-pressed', String(selected));
    $('#mic-' + i).setAttribute('aria-label', (selected ? 'Mute' : 'Enable ') + name + 'Microphone');
    $('#mic-' + i).disabled = busy && !active;
    $('[data-side="' + i + '"]').classList.toggle('active', selected);
    $('#mic-state-' + i).textContent = selected ? 'Listening · Click to mute' : busy ? 'Muted' : 'Click to speak';
    if (!selected) $('#level-' + i).style.width = '0%';
  });
  if (active) $('#notice').textContent = current.speaker < 0 ? 'Both sides are muted. Click either side to continue.' : names()[current.speaker] + ' is speaking. Click the other side to switch.';
  $('#export').disabled = !events.length;
}
function selectSpeaker(index) {
  if (!current) { start(index); return; }
  if (current.phase !== 'listening') return;
  current.speaker = current.speaker === index ? -1 : index;
  current.epoch++;
  current.stream.getAudioTracks().forEach(track => { track.enabled = current.speaker >= 0; });
  current.node.port.postMessage({ type: 'select', enabled: true, speaker: current.speaker, epoch: current.epoch });
  render();
}
function releaseAudio(session) {
  session.node?.port.postMessage({ type: 'select', enabled: false, speaker: -1, epoch: ++session.epoch });
  session.stream?.getTracks().forEach(track => track.stop());
  session.source?.disconnect(); session.node?.disconnect();
  if (session.context?.state !== 'closed') session.context?.close().catch(() => {});
  clearInterval(session.watchdog);
}
function closeSession(session, message, error) {
  releaseAudio(session); clearTimeout(session.deadline);
  session.ws?.close();
  if (current !== session) return;
  current = null;
  if (error) setError(error);
  status(message); $('#notice').textContent = message; render();
}
function finish() {
  const session = current;
  if (!session || session.phase === 'finishing') return;
  if (session.phase !== 'listening') { closeSession(session, 'Connection cancelled.'); return; }
  session.phase = 'finishing'; releaseAudio(session); render();
  status('Stopping'); $('#notice').textContent = 'Microphone closed; waiting for final transcripts…';
  session.ws.send(JSON.stringify({ action: 'finish' }));
  session.deadline = setTimeout(() => closeSession(session, 'Session ended. Transcription may be incomplete.', 'Timed out waiting for final transcripts.'), 20000);
}
function renderTranscript(event) {
  const index = { 'zoom:1': 0, 'zoom:2': 1 }[event.speaker_id];
  if (index === undefined) return;
  const feed = $('#transcript-' + index); feed.querySelector('.empty')?.remove();
  const row = document.createElement('div'); row.className = 'entry';
  const time = document.createElement('small'); time.textContent = clock(event.timestamp_ms);
  const text = document.createElement('p'); text.textContent = event.text;
  row.append(time, text); feed.append(row); feed.scrollTop = feed.scrollHeight;
}
async function start(speaker = 0) {
  if (current) return;
  setError();
  if (names().some(name => !name)) { setError('Enter a name for each speaker.'); return; }
  const session = { phase: 'starting', speaker, epoch: 0, sequence: 0 };
  current = session; events = []; result = null;
  [0, 1].forEach(i => { $('#transcript-' + i).innerHTML = '<p class="empty">Waiting for speech…</p>'; });
  $('#timeline').textContent = '00:00'; render(); status('Connecting'); $('#notice').textContent = 'Opening the microphone and transcription connection…';
  session.deadline = setTimeout(() => closeSession(session, 'Connection failed', 'Connection timed out. Try again.'), 20000);
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone access requires localhost or trusted HTTPS.');
    const device = $('#input-device').value;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true,
      ...(device ? { deviceId: { exact: device } } : {}) } });
    if (current !== session) { stream.getTracks().forEach(track => track.stop()); return; }
    session.stream = stream;
    stream.getAudioTracks().forEach(track => track.addEventListener('ended', () => {
      if (current === session && session.phase === 'listening') closeSession(session, 'Microphone disconnected', 'Check the microphone and start again.');
    }));
    const context = new AudioContext({ sampleRate: 32000 }); session.context = context;
    if (context.sampleRate !== 32000) throw new Error('This browser does not support 32 kHz audio. Use Chrome.');
    await context.resume();
    await context.audioWorklet.addModule(new URL('./multitrack-worklet.js', import.meta.url));
    if (current !== session) return;
    const node = new AudioWorkletNode(context, 'participant-capture'); session.node = node;
    session.source = context.createMediaStreamSource(stream); session.source.connect(node).connect(context.destination);
    const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/multitrack-audio'); session.ws = ws;
    node.port.onmessage = ({ data }) => {
      if (current !== session || session.phase !== 'listening' || ws.readyState !== WebSocket.OPEN) return;
      if (ws.bufferedAmount > 256 * 1024 || performance.now() - session.lastFrame > 1500) {
        closeSession(session, 'Audio transmission stopped', 'Audio transmission is backed up. Keep this page in the foreground and try again.'); return;
      }
      session.lastFrame = performance.now();
      const packets = [silence, silence];
      if (data.epoch === session.epoch && data.speaker === session.speaker && data.speaker >= 0) {
        packets[data.speaker] = btoa(String.fromCharCode(...new Uint8Array(data.pcm)));
        const pcm = new Int16Array(data.pcm);
        const rms = Math.sqrt(pcm.reduce((sum, value) => sum + (value / 32768) ** 2, 0) / pcm.length);
        $('#level-' + data.speaker).style.width = Math.min(100, rms * 400) + '%';
      }
      ws.send(JSON.stringify({ action: 'frame', sequence: session.sequence++, tracks: packets }));
      $('#timeline').textContent = clock(session.sequence * 20);
    };
    ws.onopen = () => {
      if (current !== session) { ws.close(); return; }
      ws.send(JSON.stringify({ action: 'start', language: $('#language').value, tracks: names().map(name => ({ name })) }));
    };
    ws.onmessage = ({ data }) => {
      if (current !== session) return;
      const event = JSON.parse(data); events.push(event); $('#export').disabled = false;
      if (event.type === 'ready') {
        clearTimeout(session.deadline); session.phase = 'listening'; session.lastFrame = performance.now();
        node.port.postMessage({ type: 'select', enabled: true, speaker, epoch: session.epoch });
        session.watchdog = setInterval(() => {
          if (performance.now() - session.lastFrame > 3000) closeSession(session, 'Microphone input stopped', 'Audio capture stopped. Start again.');
        }, 1000);
        status('Listening'); render();
      } else if (event.type === 'transcript') renderTranscript(event);
      else if (event.type === 'completed') { result = event; closeSession(session, 'Discussion ended. Start again anytime.'); }
      else if (event.type === 'failed') closeSession(session, 'Transcription failed. Received records have been preserved.',
        event.reason === 'missing_deepgram_key' ? 'The server is missing DEEPGRAM_API_KEY.' : 'Transcription connection failed. Check the network and Deepgram configuration.');
    };
    ws.onerror = () => { if (current === session) closeSession(session, 'Connection failed', 'Cannot connect. Another discussion session may already be running.'); };
    ws.onclose = () => { if (current === session) closeSession(session, 'Connection closed. Transcription may be incomplete.'); };
  } catch (error) {
    closeSession(session, 'Could not start the discussion', error.name === 'NotAllowedError' ? 'Allow microphone access in the browser and try again.' : error.message);
  }
}
async function devices() {
  try {
    const list = await navigator.mediaDevices.enumerateDevices(), select = $('#input-device'), previous = select.value;
    select.replaceChildren(new Option('System default', ''));
    list.filter(device => device.kind === 'audioinput' && device.deviceId).forEach((device, index) => {
      select.add(new Option(device.label || ('Microphone ' + (index + 1)), device.deviceId));
    });
    if ([...select.options].some(option => option.value === previous)) select.value = previous;
  } catch { setError('Cannot list microphones. Check browser permissions.'); }
}
[0, 1].forEach(i => {
  $('#mic-' + i).onclick = () => selectSpeaker(i);
  $('#speaker-' + i).oninput = render;
});
$('#start').onclick = () => start(0); $('#stop').onclick = finish; $('#devices').onclick = devices;
$('#export').onclick = () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify({ mode: 'deepgram', simulated_participants: true, result, events }, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = url; link.download = 'sparkie-discussion.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
window.addEventListener('pagehide', () => { if (current) closeSession(current, 'Ended'); });
render();
