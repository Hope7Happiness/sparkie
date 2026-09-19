// Correlate both kinds of speech with the request that produced them.
export function deriveTrials(state) {
  const trials = [];
  const byId = new Map();
  const textById = new Map();
  for (const event of state.events || []) {
    if (event.type === 'transcript') textById.set(event.event_id, event.text);
    if (event.type === 'wake') {
      const trial = { id: event.response_id || event.event_id, text: textById.get(event.event_id) || 'Sparkie',
        at: event.elapsed_ms, answerRequested: !!event.answer_requested, stage: 'acknowledgement' };
      trials.push(trial); byId.set(trial.id, trial);
    }
    const trial = event.response_id ? byId.get(event.response_id) : trials.at(-1);
    if (!trial) continue;
    if (event.type === 'playback_timing') {
      if (event.phase === 'answer') {
        trial.answerTotal = event.utterance_end_to_dac_estimate_ms;
        trial.answerPlayback = event.detection_to_dac_estimate_ms;
      } else {
        trial.ackTotal = event.utterance_end_to_dac_estimate_ms;
        trial.ackPlayback = event.detection_to_dac_estimate_ms;
      }
    }
    if (event.type === 'playback_timing_unavailable') trial.invalid = true;
    if (event.type === 'thinking') trial.stage = 'thinking';
    if (event.type === 'answer') {
      trial.answer = event.text;
      trial.textReady = event.detection_to_answer_text_ms;
      trial.inference = event.inference_ms;
      trial.stage = 'synthesis';
    }
    if (event.type === 'answer_audio_ready') trial.synthesis = event.synthesis_ms;
    if (event.type === 'answer_playing') trial.stage = 'speaking';
    if (event.type === 'answer_completed') trial.answerCompleted = event.utterance_end_to_answer_completed_ms;
    if (event.type === 'response_completed') trial.stage = 'completed';
    if (event.type === 'response_failed') { trial.stage = 'failed'; trial.failurePhase = event.phase; }
    if (event.type === 'response_cancelled') trial.stage = 'cancelled';
  }
  for (const trial of trials) {
    if (['ended', 'failed'].includes(state.status) && !['completed', 'failed', 'cancelled'].includes(trial.stage)) trial.stage = 'cancelled';
    trial.recognition = trial.ackTotal - trial.ackPlayback;
    const reliable = state.timingReliable && !trial.invalid;
    trial.ackValid = reliable && Number.isFinite(trial.ackTotal) && trial.ackTotal >= 0 && trial.recognition >= 0;
    trial.answerValid = reliable && Number.isFinite(trial.answerTotal) && trial.answerTotal >= 0;
    trial.total = state.options?.responseMode === 'qa' ? trial.answerTotal : trial.ackTotal;
    trial.playback = state.options?.responseMode === 'qa' ? trial.answerPlayback : trial.ackPlayback;
    trial.valid = state.options?.responseMode === 'qa' ? trial.answerValid : trial.ackValid;
    trial.textTotal = trial.ackValid && Number.isFinite(trial.textReady) ? trial.recognition + trial.textReady : undefined;
    if (!reliable) trial.answerCompleted = undefined;
  }
  return trials;
}
