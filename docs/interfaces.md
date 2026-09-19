# Phase 0 接口约定

## 当前 primitive 的音频边界

新增 `src/sparkie/audio.py`：`AudioFrame(sequence, pcm, sample_rate)`，PCM 为单声道 S16LE。`AudioMeeting` 接口提供 `join()`、异步 `audio()`、`play_audio(pcm, sample_rate)`、`stop_speaking()` 和 `leave()`。音频版 primitive 使用此接口；下方早期 `MeetingAdapter.speak(text)` 是规划中的文字层接口，当前 engine 不调用它。会议接入和语音合成模块在此边界分别接 Zoom 与 Deepgram TTS。

Deepgram 转录后进入既有 `TranscriptEvent`；`timestamp_ms` 优先使用流内最后一个识别词结束时间，无词级时间戳时退回结果段结束时间。SDK 输入要统一时间基准并过滤自身回声。具体替换路径见 [primitive](primitive.md)。

Python 数据类型见 `src/sparkie/contracts.py`。接入 SDK 可以使用其他语言，但交换数据必须符合本约定。

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
