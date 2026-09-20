<p align="center"><img src="docs/assets/sparkie-icon.png" alt="Three people and an AI secretary in a meeting" width="180"></p>

# Sparkie

**An AI secretary that joins your Zoom meeting, follows the conversation, and gets things done.**

Sparkie joins as a participant. It listens while your team talks, responds when addressed, and hands work to a background agent so the meeting can keep moving. Ask it to research a question, write a document, edit a file, or carry out a task in the project. When the work is ready, it reports back by voice.

> “Sparkie, turn that into a short video outline and save it in the project.”
>
> Keep discussing the recording plan. Then ask it to add the roles you just agreed on to the same file.

## What works today

The current macOS Zoom path connects real meeting audio, participant transcripts, context-aware voice responses, and background execution. Recent local Zoom sessions include discussing competing demo ideas, creating an outline, and delegating follow-up edits. The team has also reported good results with the current semantic turn-completion setting.

- **Listen in context.** Human speech is transcribed per Zoom participant and retained for later questions.
- **Speak when addressed.** Call “Sparkie” to ask a question or delegate work. Ordinary team discussion stays in context without requiring a reply.
- **Handle pauses and interruptions.** Semantic turn detection groups speech before wake routing; text-confirmed human speech can interrupt an ongoing reply.
- **Work during the meeting.** A selectable Devin or Codex CLI worker can search, use tools, read and write files, and execute commands while the foreground stays available.
- **Continue the work.** Ask for progress, cancel a task, or request another edit to an existing result. Running Devin tasks also accept request updates.

This is a hackathon prototype with working real-session evidence, not a claim of universal latency or long-session reliability. See [current speech handling and validation](docs/semantic-turn-detection.md).

## How it works

```text
Zoom Meeting SDK — per-participant human audio
    ├── Deepgram — words, transcripts, speech activity
    └── Realtime semantic VAD — completed speech turns
                  ↓
         Wake routing — was Sparkie addressed?
                  ↓
         GPT Realtime — contextual voice conversation
                  ├── audio reply → Zoom microphone
                  └── delegated task → Devin / Codex CLI
                                           ↓
                                  tools, files, commands
                                           ↓
                                  result → voice report
```

The current example configuration uses **gpt-realtime-2.1** for voice and semantic turn detection, **Deepgram nova-3** for transcription, **Gemini via a separate Devin process** for semantic wake routing, and **Devin SWE 1.6 Fast** for background tasks. Codex remains selectable through `SPARKIE_TASK_BACKEND=codex`. Provider adapters are separate from shared meeting contracts.

The background worker receives finalized transcript context available when the task is delegated. Later decisions should be sent as an explicit update or follow-up request. A task acknowledgement means work was queued; completion must be checked against the actual result.

## Run a real Zoom session on macOS

Prerequisites: Python 3.11+, `uv`, a macOS build environment, the supported Zoom Meeting SDK (the native bridge targets 7.1.5), Deepgram and OpenAI API access, and a logged-in Devin or Codex CLI. The meeting host must admit Sparkie and grant the recording/raw-audio permission required by the SDK. External meetings may require additional Zoom authorization; see the setup guide.

```bash
uv sync --frozen
cp .env.example .env
```

Fill in `.env` locally. It is ignored by Git. Set the Zoom SDK credentials, meeting details, `ZOOM_MACOS_SDK_PATH`, `OPENAI_API_KEY`, and `DEEPGRAM_API_KEY`. The template selects macOS, English transcription, semantic turn detection, Devin tasks, and semantic wake routing. Authenticate the selected CLI separately; semantic wake routing also requires Devin when enabled.

```bash
uv run --frozen python scripts/zoom-sanity.py build --platform macos
uv run --frozen python scripts/zoom-sanity.py check --platform macos
ZOOM_PLATFORM=macos bash scripts/zoom.sh --language en-US --seconds 3600 --response-mode realtime
```

Wait for `listening_ready`, then speak normally:

> “Sparkie, what were the two options we just discussed?”
>
> “Sparkie, write a short outline from that and save it as demo-outline.md in this project.”
>
> “Sparkie, add the roles we just agreed on to the end of that file.”

Use distinct Zoom display names and headphones. A teammate can open the resulting file in an editor and manually share that window. Finish pending work before stopping the session.

For exact SDK installation, authorization, and troubleshooting: [macOS setup](docs/zoom-macos.md), [manual configuration](docs/manual-setup.md), and [Realtime operation](docs/realtime.md).

### Execution and credentials

The Realtime task worker runs in the project workspace with filesystem, shell, network, and configured tool access, without an approval gate or per-task timeout. Delegate tasks accordingly. Both CLI backends reuse their CLI login; the voice OpenAI API key is not used for Codex CLI billing. Voice and per-participant semantic detectors make their own API calls.

Session records are written under `output/zoom/<session>/`, including `transcript.jsonl`, `events.jsonl`, `run.json`, and `tasks.json` when tasks exist. These local outputs may contain meeting content and are ignored by Git. Generated assistant text is not proof that every word was heard remotely, especially after an interruption.

## Offline smoke checks

After dependency installation, these simulations require no API keys, SDK downloads, Docker, or network calls:

```bash
uv run --frozen python -m unittest discover -s tests -v
bash scripts/primitive.sh
bash scripts/demo.sh
```

Simulation results are labeled as simulated. They test the software flow; they do not establish real Zoom or remote audio behavior. Legacy `wake` / `qa` modes use the older Deepgram STT/TTS path and remain available for diagnostics. The default legacy TTS is Aura-2 English; transcription language support does not imply matching TTS support.

## Demo film

Three teammates meet to plan Sparkie’s demo video. Sparkie is the fourth participant: it weighs in on the opening, writes the outline while the team discusses filming, then adds their agreed roles. The meeting they are recording becomes the demo itself.

Open [the shooting script](docs/sparkie-demo-script.html) in a browser for English dialogue, Chinese rehearsal notes, shot directions, response-dependent branches, and recording checks. Suggested runtime is 2–3 minutes after editing; actual interactions determine the pace. Open the local HTML file directly to use the rehearsal controls.

The [square icon](docs/assets/sparkie-icon.png) shows an AI secretary as an equal participant in the call.

## Current boundaries

- The main demo path is macOS Zoom and English. Linux and legacy modes have different input behavior.
- Sparkie does not inspect video or shared-screen content. File access comes from the delegated worker’s tools.
- Per-participant tracks distinguish Zoom connections, not multiple people sharing one microphone. Human microphone echo can still re-enter the transcript.
- Speech completion and wake decisions are probabilistic. Response timing varies with turn detection, providers, task complexity, and playback.
- If participant input fails, the system records a coverage gap and stops automatic output rather than silently accepting incomplete input. Realtime does not automatically reconnect.
- Email delivery and proactive unsolicited participation are outside this demo. Tool actions require the relevant integration and a user-delegated request.

## Team and development

[@Hope7Happiness](https://github.com/Hope7Happiness), [@YIFANK](https://github.com/YIFANK), and [@bowenyu066](https://github.com/bowenyu066) rotate one coding/integration lead with two teammates testing runnable builds. There is no permanent module ownership. See [team workflow](docs/team-first-steps.md).

Before core changes, read `prompt`, [interface contracts](docs/interfaces.md), and [team workflow](docs/team-first-steps.md). Run the checks above and hand off the commit, run command, tested scope, and known limitations. Reproduce, fix, and verify a reported scenario before closing its bug. Completed verified changes are committed locally; pushing or opening a PR requires an explicit request.

The original [product plan](prompt) contains future scope as well as implemented work. This README describes the current demo path.
