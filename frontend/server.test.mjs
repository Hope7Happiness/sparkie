import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { SessionController, validateOptions, allowedRequest } from './server.mjs';
import { networkInterfaces } from 'node:os';

test('LAN addresses allow same-origin API and audio while unrelated origins and hosts are rejected', () => {
  for (const { address, family } of Object.values(networkInterfaces()).flat()) {
    const host = `${family === 'IPv6' ? `[${address}]` : address}:5178`;
    assert.equal(allowedRequest({ headers: { host, origin: `http://${host}` } }, 5178, true), true);
    assert.equal(allowedRequest({ headers: { host, origin: 'https://unrelated.example' } }, 5178), false);
    assert.equal(allowedRequest({ headers: { host } }, 5178, true), false);
  }
  assert.equal(allowedRequest({ headers: { host: 'unrelated.example:5178', origin: 'http://unrelated.example:5178' } }, 5178), false);
});
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

test('realtime launches separate runner and validates control messages', () => {
  const child = new EventEmitter();
  child.stdout = new PassThrough(); child.stderr = new PassThrough(); child.stdin = new PassThrough(); child.kill = () => {};
  let command;
  const controller = new SessionController((exe, args, options) => { command = { args, options }; return child; });
  controller.start({ language: 'zh-CN', echoMode: 'headphones', responseMode: 'realtime', seconds: 120, inputDevice: '', outputDevice: '' });
  assert.equal(command.args[1], 'sparkie.realtime_session');
  assert.equal(command.options.stdio[0], 'pipe');
  assert.throws(() => controller.control({ action: 'arbitrary' }));
  controller.control({ action: 'interrupt' });
  assert.equal(JSON.parse(child.stdin.read().toString()).action, 'interrupt');
  child.emit('close', 0, null);
});

test('bounded event history retains monotonic cursors after rollover', () => {
  const { controller, child } = harness();
  controller.start(options);
  for (let i = 0; i < 2010; i++) child.stdout.write('{"type":"test"}\n');
  assert.equal(controller.state.events.length, 2000);
  assert.equal(controller.state.events.at(-1).sequence, 2010);
  child.emit('close', 0);
});

test('browser input stalls preserve tasks and recover on incoming audio without child meter events', () => {
  const { controller, child, advance } = harness();
  child.stdin = new PassThrough();
  controller.start({ ...options, responseMode: 'realtime', transport: 'browser', seconds: 0 });
  assert.equal(controller.deadlineTimer, undefined);
  child.stdout.write('{"type":"listening_ready"}\n');
  advance(7000); controller.snapshot(); controller.expire();
  assert.equal(controller.state.audioStalled, true);
  assert.match(controller.state.warning, /后台任务仍在继续/);
  assert.deepEqual(child.signals, []);
  controller.audioCommand({ action: 'audio_input', sequence: 0, pcm: 'AAA=' });
  assert.equal(controller.state.audioStalled, false);
  assert.equal(controller.state.warning, undefined);
  for (let i = 0; i < 3; i++) {
    advance(5000); controller.snapshot();
    controller.audioCommand({ action: 'audio_input', sequence: i + 1, pcm: 'AAA=' });
    controller.expire();
  }
  assert.deepEqual(child.signals, []);
  controller.stop(); child.emit('close', 0);
  assert.equal(controller.state.status, 'ended');
});

test('partial transcript replaces preview without filling final history, and clears on final/close', () => {
  const { controller, child } = harness();
  controller.start(options);
  for (let i = 0; i < 2010; i++) child.stdout.write(JSON.stringify({type:'transcript_partial',text:'draft '+i})+'\n');
  assert.equal(controller.state.partialTranscript, 'draft 2009');
  assert.equal(controller.state.events.length, 0);
  child.stdout.write(JSON.stringify({type:'transcript',text:'final text'})+'\n');
  assert.equal(controller.state.partialTranscript, '');
  assert.equal(controller.state.events.length, 1);
  child.stdout.write(JSON.stringify({type:'transcript_partial',text:'unfinished'})+'\n');
  child.emit('close', 0);
  assert.equal(controller.state.partialTranscript, '');
});

test('repeated cancelled replies show a temporary hint without stopping the session', () => {
  const { controller, child, advance } = harness();
  controller.start(options);
  const emit = event => child.stdout.write(JSON.stringify(event)+'\n');
  emit({type:'listening_ready'});
  emit({type:'user_speech_started'});
  assert.equal(controller.state.speechActive, true);
  assert.equal(controller.state.speechStartedAt, 1000);
  emit({type:'user_speech_stopped'});
  assert.equal(controller.state.speechActive, false);
  emit({type:'realtime_response_done',status:'cancelled'});
  assert.equal(controller.state.voiceHint, undefined);
  advance(1000);
  emit({type:'realtime_response_done',status:'cancelled'});
  assert.match(controller.state.voiceHint, /打断/);
  assert.equal(controller.state.status, 'listening');
  emit({type:'assistant_transcript',text:'Hello'});
  assert.equal(controller.state.voiceHint, undefined);
  child.emit('close', 0);
});

test('linked voice workspace survives event rollover and end, but not a new session', () => {
  const { controller, child } = harness();
  controller.start({ ...options, responseMode: 'realtime', transport: 'browser', outputDevice: '' });
  child.stdout.write(JSON.stringify({ type: 'workspace_linked', workspace_id: 'ws_abcd' }) + '\n');
  for (let i = 0; i < 2001; i++) child.stdout.write('{"type":"fixture"}\n');
  assert.equal(controller.snapshot().workspaceId, 'ws_abcd');
  assert.ok(!controller.state.events.some(e => e.type === 'workspace_linked'));
  child.emit('close', 0);
  assert.equal(controller.snapshot().workspaceId, 'ws_abcd');
  controller.start(options);
  assert.equal(controller.snapshot().workspaceId, undefined);
  child.emit('close', 0);
});
