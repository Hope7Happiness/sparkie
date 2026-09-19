# Sparkie

Read `prompt`, `docs/interfaces.md`, and `docs/team-first-steps.md` before changes.
Phase 0 priority: prove real meeting join → transcript/audio → wake → fixed audio reply.
Do not describe mock results as evidence of real platform capability.
Keep provider adapters separate from shared contracts. The current coding lead owns integration and documents contract changes for testers.
Workflow: one rotating human coding lead works with the coding agent; the other two teammates test runnable builds and report reproducible feedback. No fixed module ownership. Initially @Hope7Happiness and Codex build the primitive; @YIFANK and @bowenyu066 test it. Refer to teammates by these GitHub usernames rather than A/B/C or ambiguous pronouns. Rotation order after the first round is not assigned.
Each handoff includes the commit, run command, test scope and known limitations. Close reported bugs only after reproducing, fixing and verifying the reported scenario.
Never invent decisions, action owners, deadlines, citations, or successful task results.
No email sending, video processing, proactive interruption, or precise diarization in the initial scope.
Selected stack: Zoom Meeting SDK (body), Deepgram (ears and mouth), Codex CLI or OpenAI API (brain).
Default TTS is Aura-2 English; do not imply Chinese STT support means Chinese TTS support.
Default fixed-reply simulation must never call a live backend. Codex backend reuses CLI login, excludes project keys from child env, and uses a read-only temporary workspace.
Simulation must remain runnable without API keys, Docker, SDK downloads, or network calls after dependency installation.
Run `uv run --frozen python -m unittest discover -s tests -v`, `bash scripts/primitive.sh`, and `bash scripts/demo.sh` after core changes.
