# Sparkie

Read `prompt`, `docs/interfaces.md`, and `docs/team-first-steps.md` before changes.
Phase 0 priority: prove real meeting join → transcript/audio → wake → fixed audio reply.
Do not describe mock results as evidence of real platform capability.
Keep provider adapters separate from shared contracts. Agree on contract changes with all owners.
Never invent decisions, action owners, deadlines, citations, or successful task results.
No email sending, video processing, proactive interruption, or precise diarization in the initial scope.
Selected stack: Zoom Meeting SDK (body), Deepgram (ears and mouth), Codex CLI or OpenAI API (brain).
Default TTS is Aura-2 English; do not imply Chinese STT support means Chinese TTS support.
Default fixed-reply simulation must never call a live backend. Codex backend reuses CLI login, excludes project keys from child env, and uses a read-only temporary workspace.
Simulation must remain runnable without API keys, Docker, SDK downloads, or network calls after dependency installation.
Run `uv run --frozen python -m unittest discover -s tests -v`, `bash scripts/primitive.sh`, and `bash scripts/demo.sh` after core changes.
