# Zoom 会议内语音问答

现已接通真实闭环：Zoom 会议音频 → Deepgram STT → Sparkie 唤醒 → Codex Terra Medium → Deepgram TTS → Zoom 虚拟麦克风 → 其他参会者。沿用已验证的 Linux ARM64 Meeting SDK **7.0.5.3529**；macOS 原生接收探针仍保持原有用途。

## 启动

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
bash scripts/zoom.sh --language en --seconds 600
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
- 音频为单声道 PCM16、32 kHz。输入队列有上限；断线、无音频、队列溢出、虚拟麦克风不可用会明确失败，不默默丢帧。输出按 20 ms 分片发送。
- 为防止自身回答和参会者扬声器回声触发，播放期间及之后 350 ms 的输入替换为静音。因此该窗口内不能语音打断，也不会记住别人同时说的话。未实现全双工回声消除。
- 当前是同账号、单场会议的开发测试路径，尚未验证跨账号授权、断线重连或整场长会议稳定性。英文 STT/TTS 为默认测试路径。

## 2026-09-19 实测证据

会话 `20260919T180641Z-70565c` 使用真实 Zoom 会议。浏览器测试端以合成麦克风输入 “Sparkie, what is a WebSocket?”，机器人从 Zoom 音频识别出完整问题，Terra Medium 用约 **9.2 秒**生成答案；Deepgram 合成后，经 Zoom SDK 虚拟麦克风发送回会议。

测试端另外捕获了 **Zoom 接收到的播放音频**，转录复核得到确认语和完整答案：“A WebSocket is a persistent connection between a client and server … real-time features like chat, live updates, and multiplayer apps.” 与引擎答案一致。这里只保存合成测试输出，没有录制真人麦克风。验证文件留在本机 `output/zoom-remote-verification.json` 和 `output/zoom-remote-reply.wav`，不提交到 Git。

这次验证覆盖实际入会、音频接收、唤醒、真实推理、合成和远端收到完整语音；没有把 SDK 返回成功或离线模拟当作远端听到声音的证据。真人多次唤醒、多人讨论和长时间稳定性仍需后续验收。

接口依据：[Zoom 原始音频接收](https://developers.zoom.us/docs/meeting-sdk/linux/default-ui/advanced-features/raw-data/) 和 [虚拟麦克风接口](https://marketplacefront.zoom.us/sdk/meeting/linux/rawdata__audio__helper__interface_8h_source.html)，并以本地 7.0.5 SDK 头文件与实际会议结果核对。
