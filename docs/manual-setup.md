# Configuration

Copy .env.example to .env only if no local configuration exists. Exported variables take precedence. Install dependencies with uv sync --frozen and npm --prefix frontend ci.

| Setting | Purpose |
| --- | --- |
| OPENAI_API_KEY / OPENAI_REALTIME_MODEL | Foreground voice; default gpt-realtime-2.1 |
| DEEPGRAM_API_KEY / DEEPGRAM_MODEL | Human transcripts; default nova-3 |
| DEEPGRAM_LANGUAGE | Default CLI transcription language; en-US recommended |
| SPARKIE_TASK_BACKEND | devin or codex; both reuse CLI login |
| DEVIN_MODEL | Background model; default swe-1-6-fast |
| CODEX_MODEL / CODEX_REASONING_EFFORT | Optional Codex worker configuration |
| SPARKIE_WAKE_ROUTER / SPARKIE_WAKE_MODEL | Zoom wake routing: rules or a separate tool-free Devin model |
| SPARKIE_TURN_DETECTION | Zoom turn completion: semantic_vad or deepgram |
| SPARKIE_ZOOM_MAX_STT_STREAMS | Participant stream bound, including finalization; 1–64 |
| SPARKIE_WORKSPACE_SERVER | Workspace address; default 127.0.0.1:8790 |
| SPARKIE_WEB_PORT | Frontend and Zoom share-page port; default 5178 |
| SPARKIE_INPUT_DEVICE / SPARKIE_OUTPUT_DEVICE | Native local audio device index or name |

Authenticate the selected CLI separately. Semantic wake routing needs Devin even when Codex executes tasks. Semantic turn detection adds a Realtime detector per active human speaker and incurs API usage.

Zoom requires Meeting SDK Client ID/Secret, meeting number/password, the downloaded SDK and host admission/raw-audio permission. Set ZOOM_PLATFORM to macos or linux and configure ZOOM_MACOS_SDK_PATH or ZOOM_SDK_PATH. Do not substitute Server-to-Server OAuth credentials. See [authorization](zoom-setup.md).

~~~bash
chmod 600 .env
uv run --frozen sparkie doctor
uv run --frozen sparkie devices
~~~

Doctor checks presence of keys, the selected task CLI, SDK files and platform prerequisites without printing secrets. It does not authenticate or prove meeting access. Devices lists native devices without recording. Keep keys, SDK binaries and session data out of Git. The workspace server has no user authentication; bind to loopback unless trusted LAN access is needed.
