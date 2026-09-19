# Primitive：模拟流程与真实服务可以分别验证

当前技术栈：**Zoom + Deepgram STT/TTS + Codex CLI / OpenAI API**。已验证真实 Deepgram TTS→流式 STT、Codex 上下文回答；Zoom 原生 adapter 尚未实现，真实入会与会议内音频仍未验收。

## 网页语音测试台

```bash
bash scripts/web.sh
# 打开 http://127.0.0.1:5178
```

需要 Node.js 20.19+ 或 22.12+、npm 和 uv；启动脚本安装锁定依赖。页面控制**运行服务的这台电脑**的麦克风/扬声器，不使用浏览器或手机的麦克风。选择输入输出设备、语言和 60/120/300 秒时长，点击“开始测试”，等“正在聆听”后说 Sparkie 并停顿。系统麦克风权限属于启动 Python 的程序。

页面显示实时输入电平、最终转录、每次唤醒的总延迟与识别/播放等待拆分、有效样本平均/最快/最慢值；可导出本轮 JSON。所有延迟来自同一台设备的时间戳，不把网页轮询耗时计入；发生丢帧或欠载后整轮计时标为无效。开始新一轮前可导出旧记录；原始会话日志仍在 `output/local/`。

“停止测试”结束采集；关闭全部测试页面后，无心跳 15 秒触发停止，必要时再等最多 5 秒强制结束。刷新页面会接回当前会话。同一服务只运行一轮测试；开多个页面会共享控制。服务只监听本机 5178。仅开发服务器提供音频 API；`npm --prefix frontend run build` 用于检查静态构建，产物不提供音频服务。

开发录制工具 Frontend Helper 可通过 Alt+Shift+H 打开，用于记录页面操作并生成 `fh_…` 问题编号。录制为手动启动，记录页面内容（可能含转录），保存在忽略目录 `frontend/.frontend-helper/traces/`；生产构建不包含工具。未发布 npm 的技能包使用本仓库内固定版本源码，来源见 `frontend/tooling/frontend-helper/README.md`。

2026-09-19 网页验收：桌面 1360px 与窄屏 390px 无横向溢出，无页面 JS 错误。通过页面开始真实采集，扬声器播放合成唤醒句后记录 1 次回复，设备估算总延迟 2648ms（识别等待 2491ms、播放等待 157ms），停止按钮正常结束采集；这仍是合成语音测试。35 项 Python 测试、4 项控制器测试、离线演示、前端锁定安装和构建通过。Frontend Helper 已验证真实操作录制、保存与版本信息；生产产物无 recorder 代码。

## 本地真人音频闭环

```bash
uv sync --frozen
uv run --frozen sparkie devices
bash scripts/local.sh --language en --seconds 60
```

等待 `listening_ready` 后说 **Sparkie** 或 **Sparkie, are you there?**，停顿后应听到 **I'm here.**。默认不调用 Codex/OpenAI，不需要 Zoom。Ctrl+C 停止；会话最长为 `--seconds` 指定的时间。真实麦克风音频发送给 Deepgram；只保存 transcript 与事件，不保存原始麦克风录音。

可用 `--input-device 0 --output-device 1` 选择设备，编号以本机 `devices` 结果为准。macOS 首次运行可能需要在“系统设置 → 隐私与安全性 → 麦克风”允许启动程序访问。Linux 需要系统 PortAudio 库。

默认扬声器模式在回复播放期间和结束后 350ms 将识别输入置为静音，避免声音回流。这个窗口内不支持语音打断，也不会转录用户的话；不是完整 AEC。戴耳机时加 `--echo-mode headphones` 可保持输入识别。中文输入加 `--language zh-CN`，回复仍为英文。

每次运行输出到 `output/local/<session-id>/`：`events.jsonl` 实时记录，`run.json` 保存总结。`playback_timing` 使用最后一个识别词结束时间与音频设备预计 DAC 播放时间估算，不是独立声学测量。发生输入丢帧或输出欠载时不报告延迟数值；持续输入丢帧或队列积压会报错。设备原生 blocksize 与 100ms 缓冲用于降低调度抖动。

第一轮由 `@YIFANK`、`@bowenyu066` 各记录 10 次叫醒、10 次普通对话，附 commit、设备、语言、session ID 和事件时间点。先检查能否听到回复、是否误触发及是否持续自唤醒，再评估延迟。

2026-09-19 本机验证：MacBook Neo 麦克风与扬声器、英文、12 秒会话，用扬声器播放合成的 “Sparkie, are you there?”，真实麦克风采集后触发 1 次唤醒并完成 1 次回复播放，无音频丢帧/欠载。会话 `20260919T165126Z-fe49f4` 的设备时间估算为识别唤醒到播放 150ms、最后一个词结束到播放 5252ms；响应延迟仍待优化，单次合成声学测试不能替代真人验收或独立可听延迟测量。Ctrl+C 正常退出并保存报告；35 项自动测试及两项离线演示通过。日志留在本机忽略目录，不提交 transcript。

## 默认离线模拟

```bash
uv sync --frozen
bash scripts/primitive.sh
uv run --frozen python -m unittest discover -s tests -v
```

首次安装依赖需要网络。安装后，默认 `simulate` 无需 key、网络、SDK 或 Docker，即使 `.env` 已有真实 key 也不调用它们。

`output/primitive/run.json` 标记 `mode: simulate`；`simulated-reply-*.wav` 是静音占位。示例覆盖去重、中间字幕、普通讨论不唤醒、单独叫名、bot 事件过滤、回复时持续输入、取消和错误记录。

## 真实 Deepgram

```bash
# 生成当前配置的固定回复：真实 TTS，一次短请求
uv run --frozen sparkie tts

# 用合成测试短句验证 TTS → 实时 STT → 唤醒，不采集麦克风
uv run --frozen sparkie deepgram-check

# 会议和 STT 仍模拟，仅替换为真实 TTS（会使用 API 额度）
bash scripts/primitive.sh --tts deepgram --output output/hybrid
```

真实声音输出 `output/deepgram/reply.wav`；检查产物为 `probe.wav` 与 `check.json`。检查固定使用英文短句，不覆盖 `.env` 中的中文 STT 设置。实测返回 **Sparkie, are you there?**，唤醒匹配通过。

混合模式报告标为 `hybrid-tts`，声音文件为 `deepgram-reply-*.wav`，仅代表真实语音生成，不代表 Zoom 播放成功。模拟播放器仍以固定时长运行；进程内时间不是端到端可听语音延迟。

## 推理后端

```bash
# 默认采用 .env 中的 SPARKIE_BACKEND（当前为 codex）
uv run --frozen sparkie brain-check

# 显式使用现有 Codex CLI 登录
uv run --frozen sparkie brain-check --backend codex

# 需要 OPENAI_API_KEY 和 OPENAI_MODEL
uv run --frozen sparkie brain-check --backend openai
```

Codex CLI 已实测成功，运行于临时只读目录，使用 stdin 与最终输出文件传递数据，不向 worker 传递项目 API keys。Codex 仍通过已登录账号调用云端模型，不能当作离线推理。适合后台任务的调用边界；当前仅实现上下文回答，不包含任务队列或搜索。

`Primitive(..., brain=configured_brain())` 可接入推理；固定回复 CLI 默认不启用 brain。两种真实 brain 均用英文回答，匹配当前 Deepgram 英文声音。

## 接口与状态

第一轮由 `@Hope7Happiness` 与 Codex 统一实现和集成，`@YIFANK` 与 `@bowenyu066` 测试可运行版本；后续轮换角色，模块边界不代表固定人员分工。

| 模块 | 文件 | 状态 |
| --- | --- | --- |
| 本地音频 | `local_audio.py`、`local_session.py` | 已实现麦克风/扬声器、回声静音窗口和日志；真人多次验收待进行 |
| Zoom 音频边界 | `audio.py` 的 `AudioMeeting` | 待实现原生 SDK 接入：join/audio/play_audio/stop_speaking/leave |
| 模拟会议、STT、TTS | `simulation.py` | 可运行，脚本 transcript 与静音占位 |
| Deepgram STT | `providers.py` 的 `DeepgramEars` | 真实 WebSocket 检查通过 |
| Deepgram TTS | `providers.py` 的 `DeepgramMouth` | 真实 Aura REST PCM 检查通过 |
| Codex 后端 | `backends.py` 的 `CodexBrain` | 真实非交互调用通过 |
| OpenAI API 后端 | `providers.py` 的 `OpenAIBrain` | key 认证通过，推理为模拟协议测试 |
| 唤醒与回复 | `engine.py`、`wake.py` | 非阻塞回复，最近 50 条人类 transcript 上下文 |

## 已知限制

Deepgram 当前官方 TTS 列表没有中文，因此固定回复为 **I'm here.**，英语模型不会静默接受中文文本。ElevenLabs adapter 暂保留为可选实现，默认配置和流程均不使用。

唤醒是保守称呼与问句/命令规则，接受 `Sparkie` 和 `Sparky`。部分句式可能漏检。回复中再次唤醒会记录 `response_busy` 并忽略；取消词会停止当前回复。模拟可标注 bot 来源；本地扬声器模式有静音窗口，Zoom 混合音轨回声过滤仍待实现。

尚无 Zoom native adapter、稳定重连、滚动摘要、后台任务队列、搜索和会后纪要。云端单服务通过不等于整场会议可用。人工配置见 [清单](manual-setup.md)。
