# Realtime 本地验收

唯一前端入口现在是 Realtime + Deepgram 并行转写 + Codex 后台分析。Zoom 音频接入由另一个改动处理，本改动没有改动 Zoom 实现。

## 启动

`.env` 配置 `OPENAI_API_KEY`、`DEEPGRAM_API_KEY`。默认 `OPENAI_REALTIME_MODEL=gpt-realtime-2.1`；后台使用 `CODEX_MODEL`（默认 gpt-5.6-terra），复用 `codex login`。密钥不会发给网页或 Codex 子进程。

```bash
bash scripts/web.sh
# http://127.0.0.1:5178/
# 若原端口被其他开发占用：
SPARKIE_WEB_PORT=5179 bash scripts/web.sh
```

点击开始才打开麦克风。默认英语转写、扬声器模式、五分钟。说中文时在设置中选择中文；界面语言不决定转写语言。设置可选输入输出设备、扬声器和时长。实际使用耳机时可在设置中切换耳机模式，支持语音打断；默认扬声器模式使用「打断」按钮，在回复期间暂停输入，以防自身回声触发，日志记录转写缺口。macOS 首次运行需要给启动服务的终端/应用麦克风权限。

## 验收范围

1. 直接说“你好，解释一下什么是 WebSocket”，不用叫唤醒词，检查回复是否流式出现。
2. 耳机模式在长回复中说“停一下，简短一点”，检查播放停止、旧音频不会恢复。
3. 口述几个候选方案，然后说“请把刚才几个方案交给后台，比较优缺点，列出建议”。应立即出现任务，仍可继续简单对话。
4. 任务完成后界面显示结果。开口询问结果或点击播报；不会自行抢话。
5. 取消待处理任务，确认状态取消；结束会话后麦克风释放，所有在途后台任务取消。
6. 导出完整转写，检查人类最终文本、助手生成文本、打断与覆盖缺口。任务采用委派时可用快照，之后的发言不会追加到已启动任务。

后台目前仅分析、整理、起草，不联网查资料、不发消息、不修改文件。英文/中文语音由 Realtime 输出，不走旧版 Aura 英文 TTS。实时前台约五分钟上限，结束会取消仍在运行的分析任务。转写失败时对话继续，但后续任务上下文缺失会写入日志。

## 验证记录

- 单元测试覆盖去重、完整快照、任务限流/取消、流式 PCM 拼接、播放时间、打断后的迟到音频、工具即时返回。
- 真实 API 探针已验证 `gpt-realtime-2.1` session 配置与流式音频输出。
- 另一真实探针将合成语音交给 Deepgram，获得最终文本，再通过 Codex CLI 成功生成带转写 event_id 的比较结果。这是合成语音链路验证，不等于真人麦克风或 Zoom 验收。
- 真人语音的首声延迟、音质、打断体验等待用户验收。日志 `realtime_audio_started` 使用设备估算；后台耗时见 tasks.json 的 started_at / finished_at。

官方接口参考：[Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations)、[VAD](https://developers.openai.com/api/docs/guides/realtime-vad)、[gpt-realtime-2.1](https://developers.openai.com/api/docs/models/gpt-realtime-2.1)。

## 本地扬声器自我打断修正

验收日志记录默认 headphones 模式下播放 421 ms / 330 ms 后被 speech_started 取消，echo_gated_seconds 为 0。此传输是 PortAudio，不具备 Personal Agent 中 AVAudioEngine.setVoiceProcessingEnabled 的原生回声消除。现将网页与 Realtime CLI 默认模式改成 speaker，启用已有输入静音及播放尾音保护，与 Personal Agent 未启用 Voice Processing 时的备用方案一致。无需改动 VAD 或关闭耳机模式的语音打断。音频回调回归验证了播放、流式包间停顿和尾音阶段的回音不能进入两条上游音频流，结束保护后真实输入恢复。真实设备验收需重新开始一轮会话。

## 转写语言回归

旧网页默认 en，新网页一度默认 zh-CN，英文验收出现单词粘连和错字。已恢复默认 en，设置标签明确为「转写语言」；中文仍可手动选择。Realtime 会话恢复读取 DEEPGRAM_MODEL，并在 transcription_config 事件中记录实际模型、语言和采样率，便于复现。Deepgram Nova-3 当前 multi 文档支持范围不包含中文，因此未将 multi 冒充中英自动切换。

真实接口对照（同一段合成英文 PCM16 32 kHz，仅切换 language）：zh-CN 得到 `SparkieHowreyoudoingtoday` 并遗漏后文；en 得到 `Sparkie, how are you doing today? Thank you. You. Please compare the two options.`，仍有一个重复词。本实验支持语言不匹配是此次明显退化的原因，不等于已验证真人音频完全准确。
