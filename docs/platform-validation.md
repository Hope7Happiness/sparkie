# 平台选择与验证状态

团队已选定：**Zoom = body、Deepgram = ears + mouth、Codex CLI / OpenAI API = brain**。

2026-09-19 核验了官方资料与 Zoom 官方示例源码。文档能力和账号实际开通情况分开记录：

| 能力 | 原始证据 | 本项目实测 |
| --- | --- | --- |
| 同账号 SDK 入会使用 JWT；跨账号增加审核及用户授权 | [Zoom SDK authorization](https://developers.zoom.us/docs/meeting-sdk/auth/) | 尚未实测，缺账号配置及 SDK |
| Linux SDK 原始音频接收，需要录制权限等条件 | [Zoom 官方 raw recording sample](https://github.com/zoom/meetingsdk-linux-raw-recording-sample) | 尚未实测 |
| 向会议发送 PCM16 音频 | [Linux AudioRawDataSender](https://marketplacefront.zoom.us/sdk/meeting/linux/class_i_zoom_s_d_k_audio_raw_data_sender.html) | 尚未实测 |
| Deepgram 流式转录与语言参数 | [Streaming](https://developers.deepgram.com/docs/live-streaming-audio)、[Languages](https://developers.deepgram.com/docs/models-languages-overview) | 真实英文流式转录与唤醒测试已通过 |
| Deepgram Aura 文本转语音，支持 PCM 输出 | [TTS](https://developers.deepgram.com/docs/text-to-speech) | 已真实生成英文 PCM16 mono 32kHz WAV |
| Codex 非交互上下文回答 | [Non-interactive](https://developers.openai.com/codex/noninteractive) | 使用本机 ChatGPT 登录实测成功 |
| OpenAI Responses 文本问答 | [Developer quickstart](https://developers.openai.com/api/docs/quickstart) | 仅模拟 HTTP 测试 |

第一阶段使用 Meeting SDK，因为需要一个能发声的独立参会者。RTMS 的音频输入能力不能单独证明完整双向参会体验；本次不实现 RTMS。

后续真实测试记录：SDK 版本与架构、账号归属、权限状态、入会结果、10 次唤醒延迟和成功次数、10 次非唤醒对话误触发次数。真实延迟定义为唤醒句结束至另一名参会者听到首段响应；程序内部处理时间不代替这个指标。

人工步骤见 [配置清单](manual-setup.md)。当前最小原型及其限制见 [primitive](primitive.md)。
