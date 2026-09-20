# Zoom 会议内语音 agent

默认入口现为 GPT Realtime 前台 + Deepgram 并行转写 + Codex 后台任务。完整 agent 的启动与验收见 [Realtime Zoom 验收](realtime.md#zoom-中验收完整-agent)。本轮该组合尚未真人验收。

以下保留旧 `--response-mode qa` 流程及其历史 Linux 验证记录，不能据此宣称新 Realtime 链路已验证。

现已接通真实闭环：Zoom 会议音频 → Deepgram STT → Sparkie 唤醒 → Codex Terra Medium → Deepgram TTS → Zoom 虚拟麦克风 → 其他参会者。沿用已验证的 Linux ARM64 Meeting SDK **7.0.5.3529**。macOS 原生路径（`ZOOM_PLATFORM=macos`）已实现同一闭环、无需 Docker，但尚未完成真实会议验收；以下步骤与记录仍对应 Linux 路径。

## macOS Zoom Realtime 分用户转写

当前测试入口为 Zoom Realtime，构建和多人验收步骤见 [README](../README.md) 与 [Realtime Zoom](realtime.md#zoom-中验收完整-agent)。同时发送连续混音给 Realtime、独立音轨给 Deepgram；转写与后台上下文保留 speaker_id、speaker 和会议时间。

wake/qa 已标记为 legacy，以下仅保留历史诊断/问答操作和实测证据。

## Legacy wake/qa 启动（Linux）

先完成 [Zoom 接收探针的构建和凭据配置](zoom-sanity.md)，得到 `sparkie-zoom-sanity:7.0.5` 镜像；再执行一次：

```bash
uv run --frozen python scripts/build-zoom-voice.py
```

构建脚本从本机基线镜像提取示例源码，覆盖仓库中的音频桥，再编译 `sparkie-zoom-voice:7.0.5`。SDK 文件不提交到仓库。修改 `native/zoom-linux` 后重新执行构建。

`.env` 除 Zoom 配置外，需要已有的 `DEEPGRAM_API_KEY`，以及可用的 Codex CLI 登录。默认推理模型仍是 `gpt-5.6-terra`、`medium`，无需另填 OpenAI API key。

主持人启动配置的会议。如果旧接收探针仍在运行，先停止它以免出现两个同名机器人：

```bash
uv run --frozen python scripts/zoom-sanity.py stop --platform linux
```

旧探针未运行时跳过这一步。然后启动语音版：

```bash
bash scripts/zoom.sh --language en-US --seconds 600 --response-mode qa
```

1. 主持人接纳新的 **Sparkie**，并允许其录制权限。这是读取会议原始音频的 SDK 权限；本程序不保存会议 PCM 录音。
2. 等终端出现 `listening_ready`。
3. 人类参会者加入电脑音频并取消静音，说 **“Sparkie, what is a WebSocket?”**，停顿等待回答。
4. 每次问题带上 Sparkie。已有问答引擎保留本轮最近 50 条上下文。
5. Ctrl+C 停止机器人并清理其独立容器；不会结束主持人的会议。`--seconds` 从音频链路就绪后计时，范围 1–3600 秒；入会授权最多等 120 秒。只验证固定回应可加 `--response-mode wake`。

网页 `http://127.0.0.1:5178/` 仍是本地麦克风测试台；此次 Zoom 启动入口是以上命令。语音直接发送进 Zoom，不从 Mac 本地扬声器冒充会议输出。

## 日志与边界

- `output/zoom/<session>/events.jsonl` 保存转录、答案、播放事件；`run.json` 保存结束原因与诊断。
- `zoom_playback_submitted` 表示 Zoom SDK 接受首帧；`answer_completed` 表示答案帧已按实时节奏提交完成，**不是另一端的声学延迟或收听确认**。不会套用本地设备 DAC 延迟字段。
- 音频桥仅通过 Docker 发布的随机 **127.0.0.1** 端口访问，并使用每轮随机令牌认证。只有 Zoom 配置挂载进容器，Deepgram 和推理凭据留在 Python 进程。
- 音频为单声道 PCM16、32 kHz。输入最多缓冲 1000 帧（约 10 秒），积压达到 250 帧时记录警告，消退到 50 帧以下时记录恢复；断线、无音频、队列溢出、虚拟麦克风不可用会明确失败，不默默丢帧。输出按 20 ms 分片发送。
- Linux 路径为防止自身回答和参会者扬声器回声触发，播放期间及之后 350 ms 的输入替换为静音。因此该窗口内不能语音打断，也不会记住别人同时说的话。未实现全双工回声消除。
- 当前是同账号、单场会议的开发测试路径，尚未验证跨账号授权、断线重连或整场长会议稳定性。英文 STT/TTS 为默认测试路径。

## 2026-09-19 实测证据

会话 `20260919T180641Z-70565c` 使用真实 Zoom 会议。浏览器测试端以合成麦克风输入 “Sparkie, what is a WebSocket?”，机器人从 Zoom 音频识别出完整问题，Terra Medium 用约 **9.2 秒**生成答案；Deepgram 合成后，经 Zoom SDK 虚拟麦克风发送回会议。

测试端另外捕获了 **Zoom 接收到的播放音频**，转录复核得到确认语和完整答案：“A WebSocket is a persistent connection between a client and server … real-time features like chat, live updates, and multiplayer apps.” 与引擎答案一致。这里只保存合成测试输出，没有录制真人麦克风。验证文件留在本机 `output/zoom-remote-verification.json` 和 `output/zoom-remote-reply.wav`，不提交到 Git。

这次验证覆盖实际入会、音频接收、唤醒、真实推理、合成和远端收到完整语音；没有把 SDK 返回成功或离线模拟当作远端听到声音的证据。真人多次唤醒、多人讨论和长时间稳定性仍需后续验收。

接口依据：[Zoom 原始音频接收](https://developers.zoom.us/docs/meeting-sdk/linux/default-ui/advanced-features/raw-data/) 和 [虚拟麦克风接口](https://marketplacefront.zoom.us/sdk/meeting/linux/rawdata__audio__helper__interface_8h_source.html)，并以本地 7.0.5 SDK 头文件与实际会议结果核对。


## 同源音频 A/B 方法与首轮结果

1. 只合成一次测试语音，保存发送前的 PCM；用完全相同的字节调用 `ZoomAudioMeeting.play_audio`，绕过 LLM 与重复合成。
2. 在另一参会端捕获 Zoom 实际播放输出，不录制物理麦克风；保留原始采样率。
3. 保留未处理原件，另制大致匹配语音 RMS 的两个完整试听文件，避免只因音量不同产生偏好。
4. 分析时重采样到共同采样率、做时间对齐，再查看频谱、削波和短时能量。只用总发送时长不能排除分帧抖动，波形相关性也不是主观音质评分。
5. 比较音频设置时一次只改一个因素，并继续使用同一段 PCM；基线测试本身不改变原声、降噪或发送参数。

2026-09-19 第一轮：同一段 Aura-2 Thalia 32 kHz 单声道语音长 10.240 秒，SDK 发送耗时 10.269 秒。接收端以 48 kHz 捕获，分析时滤波重采样为 32 kHz。近似匹配音量后，12–15 kHz 频带约衰减 22.8 dB，约 12 kHz 后有明显低通；接收样本未发现削波。这证明音频链路改变了频谱，但不能单凭它认定全部听感差异的主因，也未证明网络丢包或发送抖动。完整试听 A/B、原件、图表及计算限制保存在本机 `output/zoom-quality/`。

恢复问答时另复现了 STT 连接等待 2.7 秒使旧 250 帧启动队列溢出的问题。现在使用有界 1000 帧缓冲，并在 250 帧积压时警告、恢复后记录恢复事件；输入消费避免为每帧创建新的异步超时任务。超过上限仍明确失败，不静默丢弃输入。

## 接入测试的已知问题（2026-09-19）

当前版本供接入开发与短轮测试使用。最新长跑仍出现接收停顿后音频突发涌入、1000 帧队列溢出并退出；加大缓冲尚未解决稳定性问题。另收到首段声音断续、后续改善的反馈，发送节奏与远端录音正在本地调查，尚未关闭该问题。遇到 `audio_failed` / `session_failed` 后需要重新启动；不要把入会成功或一次问答通过当作长时间稳定性验收。

最新修正增加接收/转录循环的调度让步，避免缓冲突发时消费者无法运行；输出错过节拍后重新定时，避免连续快速补发。已通过 4,000 帧突发回归、原生发送停顿回归及 7 分钟真实会议恢复测试，但用户仍反馈卡顿，后续实测 SDK 报告明显媒体丢包。详见 [音频调查与验证范围](zoom-audio-investigation.md)。拉取本次原生桥改动后，需重新运行 `uv run --frozen python scripts/build-zoom-voice.py`。
