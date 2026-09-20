// One physical input, exactly one participant per capture epoch. The AudioContext is 32 kHz.
class ParticipantCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.enabled = false; this.speaker = -1; this.epoch = 0;
    this.frame = new Int16Array(640); this.offset = 0;
    this.port.onmessage = ({ data }) => {
      if (data.type !== 'select') return;
      this.enabled = data.enabled;
      this.speaker = data.speaker; this.epoch = data.epoch;
      // Discard partial speech at a switch without advancing or shrinking the shared clock.
      this.frame.fill(0);
    };
  }
  process(inputs) {
    if (!this.enabled) return true;
    const input = inputs[0]?.[0];
    for (let i = 0; i < (input?.length || 128); i++) {
      const sample = this.speaker < 0 ? 0 : Math.max(-1, Math.min(1, input?.[i] || 0));
      this.frame[this.offset++] = Math.round(sample * (sample < 0 ? 32768 : 32767));
      if (this.offset === 640) {
        this.port.postMessage({ pcm: this.frame.buffer, speaker: this.speaker, epoch: this.epoch }, [this.frame.buffer]);
        this.frame = new Int16Array(640); this.offset = 0;
      }
    }
    return true;
  }
}
registerProcessor('participant-capture', ParticipantCapture);
