import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { SessionController, validateOptions } from './server.mjs';
const options = { language: 'en', echoMode: 'speaker', responseMode: 'qa', seconds: 60, inputDevice: '', outputDevice: 1 };
function harness() {
  let now = 1000;
  const child = new EventEmitter();
  child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.signals = [];
  child.kill = signal => child.signals.push(signal);
  let argumentsUsed;
  const controller = new SessionController((...args) => { argumentsUsed = args; return child; }, () => now);
  return { controller, child, advance: ms => { now += ms; }, args: () => argumentsUsed };
}
test('reject unsafe device values and unbounded duration before spawning', () => {
  for (const override of [{ seconds: 0 }, { seconds: 301 }, { inputDevice: '--help' }, { language: 'fake' }, { outputDevice: null }, { responseMode: 'shell' }]) {
    assert.throws(() => validateOptions({ ...options, ...override }));
  }
});
test('one microphone owner, live events and clean stop preserve results', () => {
  const { controller, child, args } = harness();
  controller.start(options);
  assert.equal(args()[2].stdio[0], 'ignore');
  assert.equal(args()[1][args()[1].indexOf('--response-mode') + 1], 'qa');
  assert.throws(() => controller.start(options), /正在运行/);
  child.stdout.write('plain notice\n{"type":"listening_ready"}\n{"type":"audio_level","peak":0.4,"gated":true,"timing_reliable":false}\n{"type":"wake","event_id":"1"}\n');
  assert.equal(controller.state.status, 'listening');
  assert.equal(controller.state.level, .4);
  assert.equal(controller.state.timingReliable, false);
  assert.equal(controller.state.events.length, 2);
  controller.stop(); controller.stop();
  assert.deepEqual(child.signals, ['SIGTERM']);
  child.emit('close', 0);
  assert.equal(controller.state.status, 'ended');
  assert.equal(controller.state.events.length, 2);
  assert.equal(controller.child, null);
});
test('disconnect lease stops microphone, heartbeat extends lease', () => {
  const { controller, child, advance } = harness();
  controller.start(options); advance(14000); controller.snapshot(); advance(14000); controller.expire();
  assert.equal(child.signals.length, 0);
  advance(1001); controller.expire();
  assert.deepEqual(child.signals, ['SIGTERM']);
  assert.equal(controller.state.stopReason, 'page-disconnected');
  child.emit('close', 0);
});
test('failed child reports actionable error without exposing stderr', () => {
  const { controller, child } = harness();
  controller.start(options);
  child.stderr.write('secret-test-key'); child.emit('close', 1);
  assert.equal(controller.state.status, 'failed');
  assert.ok(!JSON.stringify(controller.state).includes('secret-test-key'));
});
test('forced-killed stop is failed, not a successful ended session', () => {
  const { controller, child } = harness();
  controller.start(options); controller.stop(); child.emit('close', null, 'SIGKILL');
  assert.equal(controller.state.status, 'failed');
  assert.equal(controller.state.exitSignal, 'SIGKILL');
  assert.match(controller.state.error, /强制停止/);
});
test('stalled input triggers visible failure despite an active browser heartbeat', () => {
  const { controller, child, advance } = harness();
  controller.start(options);
  child.stdout.write('{"type":"listening_ready"}\n');
  advance(3100); controller.snapshot(); controller.expire();
  assert.match(controller.state.warning, /停滞/);
  advance(3001); controller.snapshot(); controller.expire();
  assert.equal(controller.state.stopReason, 'audio-stalled');
  assert.deepEqual(child.signals, ['SIGTERM']);
  child.emit('close', 0);
  assert.equal(controller.state.status, 'failed');
});
test('normal input completion during final response is not mistaken for a stall', () => {
  const { controller, child, advance } = harness();
  controller.start(options);
  child.stdout.write('{"type":"listening_ready"}\n{"type":"audio_input_ended"}\n');
  advance(7000); controller.snapshot(); controller.expire();
  assert.equal(child.signals.length,0);
  child.emit('close',0);
  assert.equal(controller.state.status,'ended');
});
test('audio failure is retained even if graceful stop exits zero', () => {
  const { controller, child } = harness();
  controller.start(options);
  child.stdout.write('{"type":"audio_failed","reason":"capture_overrun"}\n');
  assert.equal(controller.state.stopReason,'audio-failed');
  child.emit('close',0);
  assert.equal(controller.state.status,'failed');
});
test('a short input stall warning clears when samples resume', () => {
  const { controller, child, advance } = harness();
  controller.start(options); child.stdout.write('{"type":"listening_ready"}\n');
  advance(3100); controller.expire(); assert.match(controller.state.warning,/停滞/);
  child.stdout.write('{"type":"audio_level","peak":0.1,"gated":false,"timing_reliable":true}\n');
  assert.equal(controller.state.warning,undefined);
  child.emit('close',0);
});
