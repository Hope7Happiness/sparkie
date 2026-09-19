# Primitive：模拟流程与真实服务可以分别验证

当前技术栈：**Zoom + Deepgram STT/TTS + Codex CLI / OpenAI API**。已验证真实 Deepgram TTS→流式 STT、Codex 上下文回答；Zoom 原生 adapter 尚未实现，真实入会与会议内音频仍未验收。

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

## 接口与负责人

| 模块 | 文件 | 状态 / 负责人 |
| --- | --- | --- |
| Zoom 音频边界 | `audio.py` 的 `AudioMeeting` | A 待实现原生 SDK 接入：join/audio/play_audio/stop_speaking/leave |
| 模拟会议、STT、TTS | `simulation.py` | 可运行，脚本 transcript 与静音占位 |
| Deepgram STT | `providers.py` 的 `DeepgramEars` | B；真实 WebSocket 检查通过 |
| Deepgram TTS | `providers.py` 的 `DeepgramMouth` | C；真实 Aura REST PCM 检查通过 |
| Codex 后端 | `backends.py` 的 `CodexBrain` | B；真实非交互调用通过 |
| OpenAI API 后端 | `providers.py` 的 `OpenAIBrain` | B；key 认证通过，推理为模拟协议测试 |
| 唤醒与回复 | `engine.py`、`wake.py` | 非阻塞回复，最近 50 条人类 transcript 上下文 |

## 已知限制

Deepgram 当前官方 TTS 列表没有中文，因此固定回复为 **I'm here.**，英语模型不会静默接受中文文本。ElevenLabs adapter 暂保留为可选实现，默认配置和流程均不使用。

唤醒是保守称呼与问句/命令规则，接受 `Sparkie` 和 `Sparky`。部分句式可能漏检。回复中再次唤醒会记录 `response_busy` 并忽略；取消词会停止当前回复。模拟可标注 bot 来源，真实混合音轨回声过滤仍待实现。

尚无 Zoom native adapter、稳定重连、滚动摘要、后台任务队列、搜索和会后纪要。云端单服务通过不等于整场会议可用。人工配置见 [清单](manual-setup.md)。
