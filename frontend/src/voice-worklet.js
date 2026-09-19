// Input and output share the browser audio graph; capture is echo-cancelled by getUserMedia.
class SparkieVoice extends AudioWorkletProcessor {
  constructor() {
    super();
    this.chunks = []; this.offset = 0; this.generation = 0;
    this.capture = new Int16Array(480); this.captureOffset = 0; this.enabled = false; this.muted = false; this.captureEpoch = 0;
    this.played = new Map(); this.pendingProgress = new Map(); this.progressFrames = 0;
    this.port.onmessage = ({ data }) => {
      if (data.type === 'mute') {
        this.muted = data.muted; this.captureEpoch = data.epoch;
        this.capture.fill(0);
      }
      if (data.type === 'enable') this.enabled = true;
      if (data.type === 'clear') { this.chunks = []; this.offset = 0; this.generation = data.generation; this.pendingProgress.clear(); }
      if (data.type === 'output' && data.generation >= this.generation) {
        if (data.generation > this.generation) { this.chunks = []; this.offset = 0; this.generation = data.generation; }
        if (this.chunks.length >= 1000) { this.port.postMessage({ type: 'error', message: 'playback_overflow' }); return; }
        this.chunks.push(data);
      }
    };
  }
  process(inputs, outputs) {
    const input = inputs[0]?.[0], output = outputs[0]?.[0];
    if (input && this.enabled) {
      for (const sample of input) {
        this.capture[this.captureOffset++] = this.muted ? 0 : Math.round(Math.max(-1, Math.min(1, sample)) * 32767);
        if (this.captureOffset === this.capture.length) {
          this.port.postMessage({ type: 'capture', epoch: this.captureEpoch, pcm: this.capture.buffer }, [this.capture.buffer]);
          this.capture = new Int16Array(480); this.captureOffset = 0;
        }
      }
    }
    if (output) {
      let pos = 0;
      while (pos < output.length && this.chunks.length) {
        const chunk = this.chunks[0];
        const size = Math.min(output.length - pos, chunk.pcm.length - this.offset);
        for (let i = 0; i < size; i++) output[pos + i] = chunk.pcm[this.offset + i] / 32768;
        pos += size; this.offset += size;
        const played = (this.played.get(chunk.item_id) || 0) + size * 2;
        this.played.set(chunk.item_id, played); this.pendingProgress.set(chunk.item_id, played);
        if (this.offset === chunk.pcm.length) { this.chunks.shift(); this.offset = 0; }
      }
      this.progressFrames += output.length;
      if (this.progressFrames >= 480) {
        for (const [item_id, played_bytes] of this.pendingProgress) this.port.postMessage({ type: 'progress', item_id, played_bytes, generation: this.generation });
        this.pendingProgress.clear(); this.progressFrames = 0;
      }
    }
    return true;
  }
}
registerProcessor('sparkie-voice', SparkieVoice);
