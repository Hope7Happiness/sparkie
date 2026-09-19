import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
function harness() {
  let Processor;
  const messages=[];
  const context=vm.createContext({ AudioWorkletProcessor:class { constructor(){this.port={postMessage:m=>messages.push(m)};} }, registerProcessor:(name,type)=>{Processor=type;} });
  vm.runInContext(readFileSync(new URL('./voice-worklet.js',import.meta.url),'utf8'),context);
  const processor=new Processor();
  return {processor,messages,send:data=>processor.port.onmessage({data})};
}
test('full duplex captures while rendering output and clear stops queued speech',()=>{
  const {processor,messages,send}=harness();
  send({type:'enable'});
  send({type:'output',generation:0,item_id:'one',pcm:new Int16Array(960).fill(16000)});
  const output=new Float32Array(480);
  processor.process([[new Float32Array(480).fill(.25)]],[[output]]);
  assert.ok(output[0]>.4);
  const capture=messages.find(m=>m.type==='capture');
  assert.ok(new Int16Array(capture.pcm)[0]>8000);
  assert.equal(messages.find(m=>m.type==='progress').played_bytes,960);
  send({type:'clear',generation:1});
  const after=new Float32Array(480);
  send({type:'output',generation:0,item_id:'one',pcm:new Int16Array(480).fill(16000)});
  processor.process([[new Float32Array(480)]],[[after]]);
  assert.ok(after.every(v=>v===0));
});
test('capture does not begin until providers are ready',()=>{
  const {processor,messages}=harness();
  processor.process([[new Float32Array(480).fill(.5)]],[[new Float32Array(480)]]);
  assert.equal(messages.length,0);
});
test('mute clears partial capture, keeps silence flowing and leaves playback audible',()=>{
  const {processor,messages,send}=harness();
  send({type:'enable'});
  processor.process([[new Float32Array(240).fill(.5)]],[[new Float32Array(240)]]);
  send({type:'mute',muted:true,epoch:1});
  send({type:'output',generation:0,item_id:'reply',pcm:new Int16Array(480).fill(16000)});
  const output=new Float32Array(480);
  processor.process([[new Float32Array(480).fill(.5)]],[[output]]);
  const muted=messages.find(m=>m.type==='capture');
  assert.equal(muted.epoch,1);
  assert.ok(new Int16Array(muted.pcm).every(v=>v===0));
  assert.ok(output.every(v=>v>.4));
  send({type:'mute',muted:false,epoch:2});
  processor.process([[new Float32Array(480).fill(.5)]],[[new Float32Array(480)]]);
  const resumed=messages.filter(m=>m.type==='capture').at(-1);
  assert.equal(resumed.epoch,2);
  assert.ok(new Int16Array(resumed.pcm).slice(0,240).every(v=>v===0));
  assert.ok(new Int16Array(resumed.pcm).slice(240).every(v=>v>16000));
});
