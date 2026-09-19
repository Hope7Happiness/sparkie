import test from 'node:test';
import assert from 'node:assert/strict';
import { deriveTrials } from './trials.js';
const wake = {type:'wake', event_id:'1', response_id:'1', answer_requested:true};
const ack = {type:'playback_timing', response_id:'1', phase:'acknowledgement', utterance_end_to_dac_estimate_ms:600, detection_to_dac_estimate_ms:100};
const answer = {type:'playback_timing', response_id:'1', phase:'answer', utterance_end_to_dac_estimate_ms:5000, detection_to_dac_estimate_ms:4500};
const derive = (events, overrides={}) => deriveTrials({events, status:'listening', timingReliable:true, options:{responseMode:'qa'}, ...overrides});
test('ack does not count as an actual answer; later answer preserves ack', () => {
  let [trial] = derive([wake,ack]);
  assert.equal(trial.ackValid,true); assert.equal(trial.valid,false);
  [trial] = derive([wake,ack,answer]);
  assert.equal(trial.total,5000); assert.equal(trial.ackTotal,600); assert.equal(trial.recognition,500);
});
test('text-ready and completion metrics remain separate and ID correlated', () => {
  const records = derive([wake,ack,{type:'wake',event_id:'2',response_id:'2'},
    {type:'answer',response_id:'1',text:'A WebSocket connection.',inference_ms:3000,detection_to_answer_text_ms:3010},answer]);
  assert.equal(records[0].textTotal,3510); assert.equal(records[0].answerTotal,5000);
  assert.equal(records[1].answerTotal,undefined);
});
test('failed synthesis keeps answer text and valid acknowledgement', () => {
  const [trial] = derive([wake,ack,{type:'answer',response_id:'1',text:'Zoom.'},{type:'response_failed',response_id:'1',phase:'answer_synthesis'}]);
  assert.equal(trial.stage,'failed'); assert.equal(trial.answer,'Zoom.'); assert.equal(trial.ackValid,true); assert.equal(trial.valid,false);
});
test('audio loss invalidates acoustic timing but keeps text and inference duration', () => {
  const [trial] = derive([wake,ack,answer,{type:'answer',response_id:'1',text:'Hi',inference_ms:3000}],{timingReliable:false});
  assert.equal(trial.ackValid,false);assert.equal(trial.answerValid,false);assert.equal(trial.inference,3000);
});
test('wake-only mode uses acknowledgement and stopped pending answer is cancelled', () => {
  assert.equal(derive([wake,ack],{options:{responseMode:'wake'}})[0].total,600);
  assert.equal(derive([wake,ack],{status:'ended'})[0].stage,'cancelled');
});
