import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
function harness() {
  let Processor;
  const messages = [];
  const context = vm.createContext({ AudioWorkletProcessor: class { constructor() { this.port = { postMessage: m => messages.push(m) }; } }, registerProcessor: (name, type) => { Processor = type; } });
  vm.runInContext(readFileSync(new URL('./multitrack-worklet.js', import.meta.url), 'utf8'), context);
  const processor = new Processor();
  return { messages, process: (count, value) => processor.process([[new Float32Array(count).fill(value)]]),
    select: (speaker, epoch, enabled = true) => processor.port.onmessage({ data: { type: 'select', speaker, epoch, enabled } }) };
}
test('switching speakers clears partial speech without moving the shared capture clock', () => {
  const h = harness();
  h.process(640, .5); assert.equal(h.messages.length, 0);
  h.select(0, 0); h.process(320, .5);
  h.select(1, 1); h.process(320, -.5);
  assert.equal(h.messages.length, 1);
  const frame = h.messages[0];
  assert.equal(frame.speaker, 1); assert.equal(frame.epoch, 1);
  const pcm = new Int16Array(frame.pcm);
  assert.ok(pcm.slice(0, 320).every(v => v === 0));
  assert.ok(pcm.slice(320).every(v => v === -16384));
  h.select(0, 2); h.process(640, .25);
  assert.equal(h.messages[1].speaker, 0);
  assert.ok(new Int16Array(h.messages[1].pcm).every(v => v > 8000));
});
test('both-muted sends silence, resume discards partial muted frame, and stop ends capture', () => {
  const h = harness();
  h.select(0, 0); h.process(320, .5);
  h.select(-1, 1); h.process(640, .5);
  assert.ok(new Int16Array(h.messages[0].pcm).every(v => v === 0));
  h.select(1, 2); h.process(320, .5);
  const resumed = new Int16Array(h.messages[1].pcm);
  assert.ok(resumed.slice(0, 320).every(v => v === 0));
  assert.ok(resumed.slice(320).every(v => v > 16000));
  h.select(-1, 3, false); h.process(640, .5);
  assert.equal(h.messages.length, 2);
});
