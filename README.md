# Sparkie

以独立参与者身份加入线上会议的实时 AI agent：安静监听，被唤醒后参与讨论、执行后台任务，并在会后整理纪要。

技术栈：**GPT Realtime = 前台语音 · Deepgram = 并行转写 · Codex / Devin CLI = 后台任务 · Zoom = 会议接入**。**wake/qa 是 legacy 诊断/问答路径，使用 Deepgram STT/TTS，不是当前产品测试入口。**

提供无 key 模拟 primitive；Deepgram 真实语音合成→流式转录检查已通过，本机 Codex CLI 的上下文回答也已通过实测。**旧 Zoom 问答链路已有一次真实会议收听实测；新 Realtime + Codex 链路已接入代码，真人验收待完成。**

Legacy 本地语音诊断入口：`bash scripts/local.sh --language en-US --seconds 60`。等待 `listening_ready` 后叫 “Sparkie”，应播放 “I'm here.”；按 Ctrl+C 停止。需要 Deepgram key 与麦克风权限。

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

本机网页测试台：运行 bash scripts/web.sh，打开 http://127.0.0.1:5178，使用浏览器麦克风进行 Realtime 对话与后台任务测试。详见 [Realtime](docs/realtime.md)。

Zoom 接入支持两条路径：默认 `ZOOM_PLATFORM=linux` 保留现有 Docker 配置；设为 `macos` 可使用官方 macOS SDK，无需 Docker，探针与语音桥复用同一原生二进制。两者共用 `.env` 的 Zoom 凭证。macOS 探针已通过编译与 SDK 初始化检查；macOS 语音桥已实现，真实会议收发仍待验收。

## Zoom Realtime（当前主路径）

macOS Meeting SDK 7.1.5 提供每位参会者的独立音轨给 Deepgram；分轨语音开始事件触发打断，最终文本交给 Realtime 前台回应。转写保留 Zoom 用户 ID、显示名和会议时间；多个同时发言者的音轨不会串接到前台。

配置 .env 中的 Zoom 凭据、ZOOM_MACOS_SDK_PATH、OPENAI_API_KEY、DEEPGRAM_API_KEY，以及所选后台 CLI 的登录，然后运行：

    uv sync --frozen
    uv run --frozen python scripts/zoom-sanity.py build --platform macos
    uv run --frozen python scripts/zoom-sanity.py check --platform macos
    ZOOM_PLATFORM=macos bash scripts/zoom.sh --language en-US --seconds 3600 --response-mode realtime

本轮原生协议已更新，必须重建接收器。主持人接纳 Sparkie 并允许读取原始音频所需的录制权限。默认模式就是 realtime。输出位于 output/zoom/<session>/：transcript.jsonl 保存含 speaker_id / speaker 的逐条转写，tasks.json 保存后台任务，run.json 的 transcript 按会议时间排序。

多人测试包括轮流和重叠发言、同名用户、停顿后继续、改名/进出、后台任务期间继续对话。详见 [Realtime Zoom 验收](docs/realtime.md#zoom-中验收完整-agent)。离线与合成输入测试不代表真实 Zoom 多人验收；真人重叠发言、回声和长时间稳定性仍待验证。

分轨转写过滤 Sparkie 自身用户 ID，播放期间仍记录其他用户；检测到真人开始说话后停止播放，最终文本叫到 Sparkie 才重新回应，普通讨论保持静音。Realtime 在此模式使用分轨最终文本，混音只保留静音时钟，避免重复输入和自触发。远端声学回声仍可能进入分轨转写；共用同一 Zoom 麦克风的多人仍不能分人。Linux 保留混音转写。

## Legacy：wake / qa

**wake 和 qa 是 legacy，不是当前 Zoom Realtime 产品或本轮测试入口。** wake 播放固定回复，qa 在旧 Deepgram STT/TTS 链路中加入上下文问答。scripts/local.sh 和 primitive 的历史语音闭环用于底层诊断。保留 [legacy Zoom 历史验证记录](docs/zoom-voice.md)，不能用旧链路的成功证明当前 Realtime 已通过会议验收。

仅需复查旧固定回复时，可显式运行：

    ZOOM_PLATFORM=macos bash scripts/zoom.sh --language en-US --seconds 60 --response-mode wake
