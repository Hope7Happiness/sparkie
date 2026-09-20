# Sparkie

Read `prompt`, `docs/interfaces.md`, and `docs/team-first-steps.md` before changes.
Phase 0 priority: prove real meeting join → transcript/audio → wake → fixed audio reply.
Do not describe mock results as evidence of real platform capability.
Keep provider adapters separate from shared contracts. The current coding lead owns integration and documents contract changes for testers.
Workflow: one rotating human coding lead works with the coding agent; the other two teammates test runnable builds and report reproducible feedback. No fixed module ownership. Initially @Hope7Happiness and Codex build the primitive; @YIFANK and @bowenyu066 test it. Refer to teammates by these GitHub usernames rather than A/B/C or ambiguous pronouns. Rotation order after the first round is not assigned.
Each handoff includes the commit, run command, test scope and known limitations. Close reported bugs only after reproducing, fixing and verifying the reported scenario.
Never invent decisions, action owners, deadlines, citations, or successful task results.
The initial fixed-reply primitive excludes email sending, video processing, proactive interruption, and precise diarization. The Realtime task worker may use external tools and take actions delegated by the user.
Selected stack: Zoom Meeting SDK (body), Deepgram (human transcripts), GPT Realtime (foreground voice and its own output transcript), selectable Codex or Devin CLI (background tools/reasoning via SPARKIE_TASK_BACKEND). Legacy primitive uses Deepgram TTS.
Default TTS is Aura-2 English; do not imply Chinese STT support means Chinese TTS support.
Default fixed-reply simulation must never call a live backend. The legacy fixed-reply/Q&A Codex backend reuses CLI login, excludes project keys, and uses a read-only temporary workspace. By explicit user request, the Realtime task worker instead loads existing Codex configuration, runs in the project workspace with full filesystem/shell/network/tool access and no approval gate, and has no per-task timeout. It keeps CLI login rather than using the voice OPENAI_API_KEY for billing.
Simulation must remain runnable without API keys, Docker, SDK downloads, or network calls after dependency installation.
Run `uv run --frozen python -m unittest discover -s tests -v`, `bash scripts/primitive.sh`, and `bash scripts/demo.sh` after core changes.

Commit completed, verified changes locally after each task. Do not push or open a pull request unless the user explicitly requests it; local implementation, verification, and commits do not authorize remote publication.
