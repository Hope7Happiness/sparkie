# Phase 0 接口约定

## 当前 primitive 的音频边界

新增 `src/sparkie/audio.py`：`AudioFrame(sequence, pcm, sample_rate)`，PCM 为单声道 S16LE。`AudioMeeting` 接口提供 `join()`、异步 `audio()`、`play_audio(pcm, sample_rate)`、`stop_speaking()` 和 `leave()`。音频版 primitive 使用此接口；下方早期 `MeetingAdapter.speak(text)` 是规划中的文字层接口，当前 engine 不调用它。会议接入和语音合成模块在此边界分别接 Zoom 与 Deepgram TTS。

Deepgram 转录后进入既有 `TranscriptEvent`；`timestamp_ms` 优先使用流内最后一个识别词结束时间，无词级时间戳时退回结果段结束时间。SDK 输入要统一时间基准并过滤自身回声。具体替换路径见 [primitive](primitive.md)。

Python 数据类型见 `src/sparkie/contracts.py`。接入 SDK 可以使用其他语言，但交换数据必须符合本约定。

## 唤醒判定

句首 Sparkie / Sparky（可带 Hi / Hey / Hello）触发唤醒，后续请求不使用词汇或句式白名单；取消词仍可取消，单独叫名字只播放确认。句中提及名字不触发；以名字开头的产品描述也会触发，这是移除句式限制后的行为。当前最终转录段仍独立处理，尚不支持跨段等待并拼接问题。

问答模式启动前另行缓存请求确认语（默认 “Let me think for a moment.”）；句首称呼后有请求时选用该音频，只叫名字时仍用普通确认。`reply.text` 始终对应实际选中的确认音频，选择过程不调用模型。

## 本地问答事件

本地 CLI `--response-mode qa` 为 `Primitive` 注入推理后端，`wake` 仍只播放固定确认。网页 `responseMode` 值为 `qa` / `wake`。每次响应以触发 transcript 的 `event_id` 作为 `response_id`；确认和答案事件都携带该 ID，不能用最新的一行记录猜测归属。

`reply` 为确认请求；`thinking` 表示生成答案；`answer` 含真实答案文本、`inference_ms` 和 `detection_to_answer_text_ms`，发生在 TTS 之前；`answer_synthesis`、`answer_audio_ready`、`answer_playing`、`answer_completed` 分别表示合成、音频就绪、提交播放和播完。`playback_timing` 的 `phase` 为 `acknowledgement` / `answer`，均使用设备预计 DAC 时间，不把确认延迟当成答案延迟。`answer_completed` 另含从最后一个词结束到完整朗读结束的时间。丢帧时声学时间估算无效；推理耗时仍可参考。

`response_failed` / `response_cancelled` 含 `phase`，保留此前已经发出的文本。上下文最多 50 条，包含人类转录和带明确前缀的历史 Sparkie 答案；`answer` 文本展示后即可进入后续请求上下文，不表示朗读一定成功。`reasoning_config` 记录本轮模型、推理强度和后端，不记录凭据。

## 会议输入与输出

`TranscriptEvent`：`meeting_id`、`event_id` 是字符串；`timestamp_ms` 是相对会议开始的非负毫秒；`text` 是转录正文；`speaker` 可为 null；`is_final` 区分中间与最终字幕；`source` 是 human 或 bot。

按 `(meeting_id, event_id)` 对最终事件去重。中间字幕不触发任务；bot 自身输出不触发唤醒。会议接入层向编排层投递事件，结束时显式调用编排层的结束处理。跨平台保持时间基准一致。

`MeetingAdapter`：异步 `join(meeting_url)`、`speak(text)`、`stop_speaking()`、`leave()`。语音与会议适配层负责文字到真实音频播放；推理层不直接调用会议 SDK。播放不得阻塞输入，打断时停止当前播放。

## 后台任务

`Task` 保存唯一 task_id、meeting_id、原始 request、创建时的 context 快照、status、result、error、sources。状态流为 queued → running → completed / failed。completed 必须有 result；failed 必须有 error；sources 只记录实际使用过的来源。

任务层使用独立异步 worker；完成结果先入队，初版仅在用户再次询问时播报，后续才验证自然停顿策略。demo.py 尚未实现 worker。

## 会议报告

至少包含 meeting_id、标题、时间、参与者、overview、key_discussion_points、decisions、action_items、open_questions、tasks、transcript。action item 格式：`{text, owner: null|string, deadline: null|string, evidence_event_ids: string[]}`。owner 和 deadline 仅在 transcript 明确提及时填写。决策及行动项应可追溯到原始事件。

离线 harness 只产出最小回放包，完整报告元数据、摘要与页面由当轮编码负责人实现。模拟产物必须保留 `mode: mock`。真实报告禁止沿用固定内容冒充模型结果。

## Zoom 独立接收探针

`scripts/zoom-sanity.py` 通过 `--platform linux|macos` 或 `ZOOM_PLATFORM` 选择运行时，默认保留 Linux Docker。两平台共用 `sparkie.zoom_config` 生成凭证；macOS 原生接收器在 `native/zoom-macos/main.m`。探针模式（无 `voice` 配置）只输出音频诊断指标；macOS 接收器另有 voice 模式实现下方音频桥协议并接入 `AudioMeeting`，其实际会议语音验收尚未完成，不能用入会成功宣称完整语音闭环。

## Zoom 音频桥

`ZoomAudioMeeting` 实现相同 `AudioMeeting` 协议，使用 Linux SDK 7.0.5；`ZoomMacAudioMeeting` 复用同一协议，由原生 macOS 应用承载 SDK（7.1.5 基线）。Docker 内的 C++ 桥通过只发布到 127.0.0.1 的随机 TCP 端口与宿主 Python 通信；macOS 应用直接绑定 127.0.0.1 的每轮随机端口，令牌经权限 600 的 config.json 传入。先发送 64 字节随机会话令牌，再交换 `type:1 byte + length:4 bytes big-endian + payload`；每条音频为单声道 PCM16 32 kHz。

SDK → Python：`H` 握手，`M`/`N` 虚拟麦克风可发送/停止，`A` 音频，`S`/`D` 首帧提交/本次音频全部提交（4 字节播放 ID），`E` 固定诊断文本。Python → SDK：`P`（4 字节播放 ID + 最多 30 秒 PCM），`C` 取消播放。单连接、单次播放；两端都有有界队列，溢出或协议错误关闭本轮。C++ 在独立线程中按 20 ms 节奏发送 PCM，音频回调只复制数据，不执行网络 I/O。

`zoom_playback_submitted` 只报告 SDK 首帧接受，不能作为另一参会者的 DAC 时间或可听确认。`zoom-audio` 不设置 `audio_origin` / `last_playback_started_at`，不输出本地设备时延估算。输入在播放及之后 350 ms 替换为静音；这会失去同时发言，也不能在该窗口内靠语音取消。
