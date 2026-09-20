# Sparkie

以独立参与者身份加入线上会议的实时 AI agent：安静监听，被唤醒后参与讨论、执行后台任务，并在会后整理纪要。

技术栈：**GPT Realtime = 前台语音 · Deepgram = 并行转写 · Codex CLI = 后台任务 · Zoom = 会议接入**。旧 wake/qa 模式仍使用 Deepgram STT/TTS。

提供无 key 模拟 primitive；Deepgram 真实语音合成→流式转录检查已通过，本机 Codex CLI 的上下文回答也已通过实测。**旧 Zoom 问答链路已有一次真实会议收听实测；新 Realtime + Codex 链路已接入代码，真人验收待完成。**

本地语音闭环已提供：`bash scripts/local.sh --language en --seconds 60`。等待 `listening_ready` 后叫 “Sparkie”，应播放 “I'm here.”；按 Ctrl+C 停止。需要 Deepgram key 与麦克风权限。

```bash
uv sync --frozen
bash scripts/primitive.sh
uv run --frozen python -m unittest discover -s tests -v
```

需要 Python 3.11+ 和 uv。首次安装依赖后，模拟模式不需要网络、SDK、Docker 或账号。生成的 `output/primitive/run.json` 与静音 WAV 均明确标为模拟产物。

- [协作方式：一人编码，两人测试反馈](docs/team-first-steps.md)
- [Zoom Linux Docker 探针：已有真实入会与音频接收记录](docs/zoom-sanity.md)
- [Zoom macOS 原生探针：配置、构建与验收](docs/zoom-macos.md)
- [人工配置清单](docs/manual-setup.md)
- [primitive 运行方式、接口和限制](docs/primitive.md)
- [技术验证记录](docs/platform-validation.md)
- [Zoom 参会与双向音频方案、联调接口](docs/zoom-agent-integration.md)
- [Zoom SDK 配置状态与本地工具](docs/zoom-setup.md)
- [完整产品计划](prompt)

协作方式：先由 [@Hope7Happiness](https://github.com/Hope7Happiness) 与 Codex 搭建 primitive，再由 [@YIFANK](https://github.com/YIFANK) 和 [@bowenyu066](https://github.com/bowenyu066) 测试；后续三人轮换一人编码、两人测试反馈，不设固定模块负责人。

最高优先级：先证明 Sparkie 可以加入真实会议，在被叫到时迅速播放“我在”。

本机网页测试台：`bash scripts/web.sh`，打开 http://127.0.0.1:5178；默认真实问答（Terra Medium）；叫出 Sparkie 后紧接问题，可查看转录、答案和分别计时的确认/回答延迟。详见 [primitive](docs/primitive.md#网页语音测试台)。

Zoom 接入支持两条路径：默认 `ZOOM_PLATFORM=linux` 保留现有 Docker 配置；设为 `macos` 可使用官方 macOS SDK，无需 Docker，探针与语音桥复用同一原生二进制。两者共用 `.env` 的 Zoom 凭证。macOS 探针已通过编译与 SDK 初始化检查；macOS 语音桥已实现，真实会议收发仍待验收。

## Zoom 会议内问答

真实 Zoom 音频 → Deepgram → Terra Medium → Zoom 语音回复已接通。构建后运行 `bash scripts/zoom.sh --language en --seconds 600`，详见 [Zoom 语音启动和实测记录](docs/zoom-voice.md)。本地网页仍使用本地麦克风模式。


Zoom 完整语音 agent（默认 GPT Realtime 前台 + Codex 后台）：

```bash
ZOOM_PLATFORM=macos bash scripts/zoom.sh --language zh-CN --seconds 3600
```

配置与验收见 [Realtime Zoom](docs/realtime.md#zoom-中验收完整-agent)。新组合已接入代码，尚未真人验收；`--response-mode wake/qa` 是旧诊断/问答路径。
