export class BrowserVoice {
  constructor(onFailure) { this.onFailure = onFailure; this.sequence = 0; this.closed = false; this.muted = false; this.captureEpoch = 0; }
  async prepare(inputDevice) {
    this.inputDevice = inputDevice;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: {
        echoCancellation: { exact: true }, noiseSuppression: true, autoGainControl: false,
        channelCount: 1, ...(inputDevice ? { deviceId: { exact: inputDevice } } : {}),
      }, video: false });
      this.settings = this.stream.getAudioTracks()[0].getSettings();
      if (this.settings.echoCancellation !== true) throw new Error('Echo cancellation is unavailable in this browser. Use Chrome.');
      this.context = new AudioContext({ sampleRate: 24000, latencyHint: 'interactive' });
      if (this.context.sampleRate !== 24000) throw new Error('This browser does not support the voice sample rate. Use Chrome.');
      await this.context.audioWorklet.addModule(new URL('./voice-worklet.js', import.meta.url));
      this.node = new AudioWorkletNode(this.context, 'sparkie-voice', { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] });
      this.source = this.context.createMediaStreamSource(this.stream);
      this.source.connect(this.node); this.node.connect(this.context.destination);
      await this.context.resume();
      this.node.onprocessorerror = () => this.fail('Audio processing stopped. Start a new conversation.');
      this.context.onstatechange = () => this.reportInputState();
    } catch (error) { this.close(); throw error; }
  }
  async recoverInput() {
    if (this.closed) throw new Error('The session ended. Start again.');
    // A user gesture can resume a suspended AudioContext. Reacquire the input
    // without replacing the WebSocket, task queue, or worklet sequence.
    await this.context.resume();
    const stream = await navigator.mediaDevices.getUserMedia({ audio: {
      echoCancellation: { exact: true }, noiseSuppression: true, autoGainControl: false,
      channelCount: 1, ...(this.inputDevice ? { deviceId: { exact: this.inputDevice } } : {}),
    }, video: false });
    if (this.closed || stream.getAudioTracks()[0].getSettings().echoCancellation !== true) {
      stream.getTracks().forEach(track => track.stop());
      throw new Error('Cannot recover the microphone with echo cancellation enabled.');
    }
    const source = this.context.createMediaStreamSource(stream);
    source.connect(this.node);
    this.source.disconnect();
    this.stream.getTracks().forEach(track => track.stop());
    this.stream = stream; this.source = source;
    this.stream.getAudioTracks().forEach(track => { track.enabled = !this.muted; });
    this.observeInput();
    this.reportInputState();
  }
  observeInput() {
    const track = this.stream.getAudioTracks()[0];
    track.onmute = () => this.reportInputState();
    track.onunmute = () => this.reportInputState();
    track.onended = () => this.reportInputState();
  }
  reportInputState() {
    if (this.closed || this.socket?.readyState !== WebSocket.OPEN) return;
    const track = this.stream.getAudioTracks()[0];
    this.send({ action: 'audio_settings', ...track.getSettings(), sampleRate: this.context.sampleRate,
      contextState: this.context.state, trackState: track.readyState, trackMuted: track.muted,
      trackEnabled: track.enabled, deviceLabel: track.label });
  }
  async connect(sessionId) {
    this.sessionId = sessionId;
    this.socket = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/audio?session=${encodeURIComponent(sessionId)}`);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Audio connection timed out.')), 5000);
      this.socket.onopen = () => { clearTimeout(timer); resolve(); };
      this.socket.onerror = () => { clearTimeout(timer); reject(new Error('Cannot connect to the audio service.')); };
    });
    this.socket.onclose = event => {
      if (this.closed) return;
      if (event.code === 1000) this.close();
      else this.fail('Audio connection closed.');
    };
    this.socket.onmessage = ({ data }) => {
      const message = JSON.parse(data);
      if (message.type === 'audio_ready') this.node.port.postMessage({ type: 'enable' });
      if (message.type === 'audio_clear') this.node.port.postMessage({ type: 'clear', generation: message.generation });
      if (message.type === 'audio_output') {
        const bytes = Uint8Array.from(atob(message.pcm), c => c.charCodeAt(0));
        const pcm = new Int16Array(bytes.buffer);
        this.node.port.postMessage({ type: 'output', item_id: message.item_id, generation: message.generation, pcm }, [pcm.buffer]);
      }
    };
    this.reportInputState();
    this.observeInput();
    this.node.port.onmessage = ({ data }) => {
      if (this.closed) return;
      if (data.type === 'capture') {
        const bytes = new Uint8Array(data.pcm);
        if (this.muted || data.epoch !== this.captureEpoch) bytes.fill(0);
        this.send({ action: 'audio_input', sequence: this.sequence++, pcm: btoa(String.fromCharCode(...bytes)) });
      } else if (data.type === 'progress') {
        // Worklet reports rendered frames; this is not an independently measured DAC timestamp.
        this.send({ action: 'audio_progress', item_id: data.item_id, generation: data.generation, played_bytes: data.played_bytes });
      } else if (data.type === 'error') this.fail('Audio playback fell behind. Start again.');
    };
  }
  setMuted(muted) {
    if (this.closed) return;
    this.muted = Boolean(muted);
    this.captureEpoch++;
    this.stream?.getAudioTracks().forEach(track => { track.enabled = !this.muted; });
    this.node?.port.postMessage({ type: 'mute', muted: this.muted, epoch: this.captureEpoch });
    this.reportInputState();
  }
  send(message) {
    if (this.closed) return;
    if (this.socket?.readyState !== WebSocket.OPEN || this.socket.bufferedAmount > 256000) return this.fail('Audio connection is congested. Start again.');
    this.socket.send(JSON.stringify(message));
  }
  fail(message) { if (this.closed) return; this.close(); this.onFailure(new Error(message)); }
  close() {
    this.closed = true;
    this.stream?.getTracks().forEach(track => track.stop());
    this.node?.disconnect(); this.source?.disconnect();
    this.context?.close().catch(() => {}); this.socket?.close();
  }
}
