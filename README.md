# Sparkie

Sparkie is an AI meeting teammate that follows discussion, answers questions and turns delegated requests into completed work. GPT Realtime handles conversation, Deepgram supplies human transcripts, and a persistent Devin or selectable Codex CLI worker handles research, files and code. Realtime decides which artifacts to present.

## Setup

Install Python 3.11+, uv, Node.js and npm. Voice needs OpenAI and Deepgram API access and a logged-in Devin or Codex CLI. Zoom additionally needs a compatible Meeting SDK and host admission/recording permissions.

~~~bash
uv sync --frozen
npm --prefix frontend ci
cp -n .env.example .env
~~~

Fill in .env locally. The template uses English transcription, Devin SWE 1.6 Fast for tasks and Gemini through a separate Devin process for Zoom wake routing. Codex is selectable through SPARKIE_TASK_BACKEND=codex. Credentials and session outputs are ignored by Git.

## Browser voice and artifacts

Run these in separate terminals:

~~~bash
uv run --frozen sparkie workspace --host 0.0.0.0 --port 8790 --worker devin
npm --prefix frontend run dev
~~~

Open http://localhost:5178/. Start a conversation, delegate work and ask Sparkie to present the result. The workspace server has no user authentication; use loopback unless trusted LAN access is needed.

The browser streams microphone audio to Realtime and transcribes it through Deepgram. Tasks and artifacts appear in the same page. The two-speaker transcription lab is at /multitrack.html. See [voice operation](docs/realtime.md) and [multitrack behavior](docs/multitrack-lab.md).

## Zoom on macOS

Set Zoom credentials, meeting details and ZOOM_MACOS_SDK_PATH in .env. The native bridge targets Meeting SDK 7.1.5. Rebuild after native source or SDK changes:

~~~bash
uv run --frozen python scripts/zoom-sanity.py build --platform macos
uv run --frozen python scripts/zoom-sanity.py check --platform macos
ZOOM_PLATFORM=macos bash scripts/zoom.sh --language en-US --seconds 3600
~~~

Keep the workspace service and frontend running for artifact sharing. The host must admit Sparkie and allow raw audio/recording. Wait for listening_ready before speaking. The macOS bridge shares the full workspace, including task progress, selected artifacts and return-to-board controls.

See [macOS setup](docs/zoom-macos.md), [configuration](docs/manual-setup.md), [Zoom authorization](docs/zoom-setup.md) and the [Linux workflow](docs/zoom-sanity.md).

## Execution and data

The background worker runs in the project workspace with filesystem, shell, network and configured tool access, without a per-task timeout or approval gate. Both backends reuse CLI login. The voice OpenAI key is not used for Codex CLI billing. Delegate only the work you intend to execute.

Workers receive finalized transcripts available at delegation. Later details require an update or follow-up. Acknowledgement means queued, not completed. Artifacts snapshot the declared document or image; presentation does not prove remote visibility.

Transcripts, events, task records and workspace state live under output/. The normal voice flow does not save raw microphone recordings. Generated text and SDK playback progress do not prove that every word was heard remotely.

## Development checks

~~~bash
SPARKIE_WORKSPACE_SERVER=127.0.0.1:1 uv run --frozen python -m unittest discover -s tests -v
npm --prefix frontend test
npm --prefix frontend run build
~~~

The workspace override isolates voice test fixtures from a running meeting. Integration tests create their own servers. Synthetic tests do not establish real Zoom or model performance. Fixed-reply simulation, Deepgram/ElevenLabs TTS and the old wake/qa CLI have been removed; local and Zoom voice use Realtime.

The [interface contracts](docs/interfaces.md) cover audio, tasks, interruption and presentation. Database migrations and active transport fallbacks remain supported.

## Presentation and rehearsal

The [shooting script](presentation/demo-script.html), original editions and Chinese rehearsal notes live in presentation/. The frontend still serves /demo-script.html and /demo-script-original.html. The [shared script service](presentation/demo-script-sharing.md) supports live collaborative editing. Other source code, interface copy and maintenance documentation use English.

## Boundaries

- Sparkie does not inspect cameras or shared-screen content. File access comes from delegated tools.
- Participant tracks identify Zoom connections, not people sharing a microphone. Acoustic echo can enter other participant tracks.
- Speech completion and wake routing are probabilistic; latency depends on devices, providers, transport and task complexity.
- Participant failures record coverage gaps and stop automatic output instead of assuming complete input. Realtime does not automatically reconnect.
- Successful builds and synthetic bridge tests are not real meeting acceptance. Verify remote audio and artifact visibility separately.

Built by [@Hope7Happiness](https://github.com/Hope7Happiness), [@YIFANK](https://github.com/YIFANK) and [@bowenyu066](https://github.com/bowenyu066).
