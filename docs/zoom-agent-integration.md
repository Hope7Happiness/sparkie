# Sparkie：Zoom 参会与双向音频方案

研究日期：2026-09-19。本文是技术方案及待验证清单，尚未完成真实入会测试。

## 结论

第一轮使用 **Zoom 原生 Meeting SDK + 一个独立音频桥接进程**，让 Sparkie 作为可见参与者加入由应用所属 Zoom 账号主持的测试会议。先播放固定的“我在”，再接语音识别和 agent。队友不必等待 Zoom 接入，可以按下文协议模拟输入开发。

RTMS 适合获取音频、字幕、视频；已查阅的 RTMS 媒体协议没有向会议注入 TTS 音频的接口，也不提供独立参与者身份。因此，RTMS 单独不能满足本项目的“参会并说话”。这是对已公布接口的判断，不代表 Zoom 未来不会增加能力。[RTMS 媒体文档](https://developers.zoom.us/docs/rtms/meetings/media/)

## 纠正与政策边界

此前根据 Linux 首页得出“Meeting SDK 不支持所有机器人”的结论过于绝对：

- [Linux 首页](https://developers.zoom.us/docs/meeting-sdk/linux/)仍写着不支持 bots / AI notetakers。
- [官方授权指南](https://developers.zoom.us/blog/app-attribution-path/)明确列出通过 OBF 加入的可见自动参会者。
- 在针对这两处矛盾的讨论中，Zoom 工作人员于 **2026-09-11** 回复，新可见 AI 会议助手目前仍是有效用例，但长期受支持的推荐方向是 RTMS。发布仍须经过审核；技术接口存在不能视为应用已获批。[直接答复](https://devforum.zoom.us/t/new-linux-meeting-sdk-visible-ai-notetaker-clarify-eligibility-versus-obf-guidance/146344)

因此建议做内部账号 PoC，并把外部客户会议的审核作为单独里程碑。不要把 SDK 成功初始化等同于可加入任何会议。

## Zoom 端配置与入会

1. Marketplace 创建 General App，名称 Sparkie；在 Features → Embed 开启 Meeting SDK，从 Basic Information 获取开发凭据 Client ID / Client Secret。[官方配置步骤](https://developers.zoom.us/docs/meeting-sdk/get-credentials/)
2. 后端用 Client Secret 签发短期 Meeting SDK JWT，包含 appKey、iat、exp、tokenExp。凭据只放服务端，不能交给页面或提交 Git。[JWT 文档](https://developers.zoom.us/docs/meeting-sdk/auth/)
3. 第一场测试由**创建应用的同一 Zoom 账号/tenant**主持，不是任意队友的个人 Zoom 账号。按官方授权表，此场景可使用 SDK JWT 入会；会议密码、等候室及身份限制仍生效。
4. SDK 初始化 → SDK 认证成功回调 → Join → 等待主持人准入 → 确认 INMEETING → 接入电脑音频。显示名使用 `Sparkie · AI assistant`。
5. 监听需要原始音频访问权限。官方示例要求主持人/联席主持人/本地录制权限，或相应 recording token。取得权限后开启 raw recording、订阅音频；权限撤回后停止消费音频。[官方音频示例](https://github.com/zoom/meetingsdk-linux-raw-recording-sample)
6. 外部账号会议另做 OAuth 与 OBF：用户授权应用，服务端获取其 OBF token，SDK 入会时同时提供 SDK JWT 与 OBF。授权用户必须已在会中，离会后相应 SDK 会话结束；外部会议还需要应用审核。OBF 不取代原始音频/录制权限。[授权规则](https://developers.zoom.us/docs/meeting-sdk/auth/) · [OBF FAQ](https://godevelopers.zoom.us/docs/meeting-sdk/obf-faq/)

SDK JWT、OAuth access token、OBF token、recording token 是不同用途的凭据，不能互换。第一轮不做替用户主持会议的 ZAK 流程，也不依赖创建会议 REST API。

## 技术实现

```text
Zoom 会议
  ↓ 原生 Meeting SDK 音频回调
Zoom bridge（C++；维护入会、权限、收发音频）
  ↓ PCM → 流式语音识别 → transcript
Agent service（队友实现；唤醒、上下文、后台任务）
  ↓ speak(text) → TTS → PCM
Zoom bridge → SDK 虚拟麦克风 → Zoom 会议
```

接收音频：使用 `GetAudioRawdataHelper()->subscribe(...)`，监听 `onOneWayAudioRawDataReceived` 或 `onMixedAudioRawDataReceived`。音频回调中只复制数据并放入有界队列，网络和模型请求移出 SDK 回调线程；按回调实际采样率重采样。首轮可先用混音流，随后切换到逐人流并过滤 Sparkie 自身，避免声音再次触发自己。[raw data 文档](https://developers.zoom.us/docs/meeting-sdk/linux/default-ui/advanced-features/raw-data/)

发送音频：`setExternalAudioSource(...)` 注册 `IZoomSDKVirtualAudioMicEvent`；在 `onMicInitialize` 保存 sender，在 `onMicStartSend` 后发送，在 `onMicStopSend` 停止，在 `onMicUninitialized` 释放引用。SDK sender 接收 16-bit PCM；将 TTS 解码/重采样为明确支持的采样率，例如单声道 16 kHz，按实时节奏送入 `send(...)`。不能直接把 MP3 文件或带 WAV 文件头的数据当作 PCM。主持人禁言及本地静音需要单独处理。[外部音源](https://marketplacefront.zoom.us/sdk/meeting/linux/class_i_zoom_s_d_k_audio_raw_data_helper.html) · [麦克风生命周期](https://marketplacefront.zoom.us/sdk/meeting/linux/class_i_zoom_s_d_k_virtual_audio_mic_event.html) · [发送接口](https://marketplacefront.zoom.us/sdk/meeting/linux/class_i_zoom_s_d_k_audio_raw_data_sender.html)

建议一个会议对应一个 bridge 进程，bridge 崩溃不拖垮 agent 服务。首轮只测单会议；音频队列限制长度，过载时报告错误并丢弃过期帧，避免长时间延迟。

运行环境：本机是 macOS arm64。若选 Linux SDK，使用与 SDK 包架构匹配的原生 Linux 主机；不要把 Apple Silicon 上的 amd64 Docker 模拟环境作为可靠验收环境。官方明确提醒 QEMU/Rosetta 跨架构模拟不受支持且不可靠。若只有这台 Mac，可以另走原生 macOS Meeting SDK，但构建和回调接口需按 macOS 文档重新适配。[环境说明](https://developers.zoom.us/docs/meeting-sdk/linux/)

Linux 起点采用[官方 raw recording 示例](https://github.com/zoom/meetingsdk-linux-raw-recording-sample)，同时参考[官方 headless 示例](https://github.com/zoom/meetingsdk-headless-linux-sample)。下载当前支持的 SDK 后按头文件调整示例并固定版本，不假设旧示例能直接编译。容器需要 PulseAudio 等音频运行依赖。

## 队友现在可以实现的接口（提案 v0）

传输先用内部 WebSocket JSON；生产环境再加身份认证和隔离。凭据和会议密码不出现在事件中。以下示例是内部协议，不是 Zoom API。

**Bridge → Agent：识别文本**

```json
{"v":1,"type":"transcript","session_id":"demo-1","event_id":"evt-1","utterance_id":"utt-1","speaker_id":"participant-2","text":"Sparkie，帮我们查一下这个问题","is_final":true,"start_ms":1200,"end_ms":3800}
```

`start_ms/end_ms` 是本次 session 开始后的毫秒偏移。partial 与 final 共享 utterance_id；event_id 用于去重；speaker_id 无法可靠判断时用 null，不猜人名。partial 可用于低延迟唤醒，正式任务去重后处理。

**Agent → Bridge：请求发言**

```json
{"v":1,"type":"speak","session_id":"demo-1","request_id":"say-1","text":"我在","interrupt":false}
```

Bridge/语音层负责 TTS；第一轮把“我在”映射为预生成音频，使入会验收不依赖模型或 TTS 网络。相同 request_id 不重复播放。串行发言；`interrupt:true` 取消当前播放并清空待播队列，然后播放新请求。增加 `cancel_speech`（带 request_id）以便后续做打断。

**Bridge → Agent/UI：状态**

```json
{"v":1,"type":"speech_status","session_id":"demo-1","request_id":"say-1","status":"started"}
```

speech_status：queued / started / finished / cancelled / failed。`finished` 只表示本地音频已提交完毕，远端是否听见必须实测。

meeting_status：connecting / waiting_room / joined / left / failed。

capabilities：`can_receive_audio`、`can_send_audio` 两个独立布尔值，附 reason；收到权限回调才更新，不能用 joined 推断音频已可用。

error：code、message、retryable；至少区分 sdk_auth_failed、join_failed、recording_permission_denied、audio_send_unavailable、disconnected。退出或授权失效时取消排队发言并清理会话。

分工：

- **我和 Zoom 接入负责人**：SDK、JWT/入会、音频收发、ASR/TTS 适配、状态与错误。
- **Agent 队友**：消费 transcript、唤醒去重、快速“我在”、上下文与后台任务；只产出 speak，不直接依赖 Zoom SDK。
- **产品/前端队友**：会议连接状态、字幕、任务列表、纪要视图；用上述模拟事件开始开发。模拟数据不计入真实会议验收。

## 第一轮验收顺序

1. Sparkie 出现在同账号测试会议的参会者列表中。
2. 另一台设备能听见 bridge 播放的固定“我在”（先独立验证发送）。
3. 主持人授予权限后，bridge 收到真实音频，语音识别产生真实文本（再独立验证接收）。
4. 真人说“Sparkie”，触发一次固定回复，其他参与者能听见，且机器人不反复唤醒自己。
5. 记录“检测到唤醒→开始发送”和“真人说完唤醒词→远端听见”的延迟。可把后者 2 秒以内设为第一轮目标，不能当成已测结果。
6. 测试撤回录制权限、主持人静音、离会、断线；确保状态可解释且没有旧发言在重连后突然播放。

当前状态：Sparkie 应用和原生 macOS SDK 7.1.5.84750 配置完成，认证成功。同账号会议已实测进入等候室并正式入会（InMeeting=3），用户确认成功；之后主持人结束会议。MIT 外部账号会议仍受错误 63 限制。下一步实现双向音频、识别与唤醒回复，详见 [配置状态](zoom-setup.md)。
