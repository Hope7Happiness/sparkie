# Two-speaker transcription lab

Run bash scripts/web.sh and open http://localhost:5178/multitrack.html. Configure DEEPGRAM_API_KEY in .env. The default model is nova-3, with English selected in the UI.

Click either microphone to speak as that participant. Clicking the other side switches identities and mutes the previous side; clicking the active side mutes both. Both buttons use one physical microphone, simulating turn-taking rather than simultaneous independent inputs. Names, language and input device are configurable.

This page calls live Deepgram only, without Zoom, Realtime or Devin. Microphone access requires localhost or trusted HTTPS. The main voice page remains a separate test surface.

## Audio contract

A 32 kHz AudioWorklet emits two 20 ms PCM16 frames per tick, real audio on the selected side and zeros on the other. Switching discards incomplete frames and stale capture-epoch messages to avoid assigning previous speech to the next participant. Finish a sentence before switching.

The /multitrack-audio WebSocket starts sparkie.multitrack_lab. The initial start contains language and tracks (2–4 names supported; the UI uses two). Each frame has a consecutive sequence and one base64 1280-byte payload per track. Time is sequence times 20 ms. Production Zoom participant decoding and ParticipantEars route independent Deepgram streams. Silence does not start recognition.

The session runs until stopped, with bounded initialization, input-idle and final-flush deadlines. Backlog, device loss or transcription failure ends the session while preserving received text. Stop releases the microphone and waits for final transcripts. Closing the page releases the process.

Records under output/multitrack/<session>/ include transcript.jsonl, events.jsonl and run.json. Raw audio is not saved. Displayed timestamps are media positions, not recognition latency.

## Verification

Python and AudioWorklet tests cover decoding, identity changes, silence, final flush and cleanup. Historical live-Deepgram tests with injected English fixtures verified left/right/left routing; they do not prove physical microphone or Zoom behavior. Acoustic accuracy and concurrent Zoom speakers require separate acceptance.
