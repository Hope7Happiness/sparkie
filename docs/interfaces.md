# Phase 0 接口约定

## 当前 primitive 的音频边界

新增 `src/sparkie/audio.py`：`AudioFrame(sequence, pcm, sample_rate)`，PCM 为单声道 S16LE。`AudioMeeting` 接口提供 `join()`、异步 `audio()`、`play_audio(pcm, sample_rate)`、`stop_speaking()` 和 `leave()`。音频版 primitive 使用此接口；下方早期 `MeetingAdapter.speak(text)` 是规划中的文字层接口，当前 engine 不调用它。会议接入和语音合成模块在此边界分别接 Zoom 与 Deepgram TTS。

Deepgram 转录后进入既有 `TranscriptEvent`；`timestamp_ms` 优先使用流内最后一个识别词结束时间，无词级时间戳时退回结果段结束时间。SDK 输入要统一时间基准并过滤自身回声。具体替换路径见 [primitive](primitive.md)。

Python 数据类型见 `src/sparkie/contracts.py`。接入 SDK 可以使用其他语言，但交换数据必须符合本约定。

## 唤醒判定

句首 Sparkie / Sparky（可带 Hi / Hey / Hello）触发唤醒，后续请求不使用词汇或句式白名单；取消词仍可取消，单独叫名字只播放确认。句中提及名字不触发；以名字开头的产品描述也会触发，这是移除句式限制后的行为。当前最终转录段仍独立处理，尚不支持跨段等待并拼接问题。

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

`scripts/zoom-sanity.py` 通过 `--platform linux|macos` 或 `ZOOM_PLATFORM` 选择运行时，默认保留 Linux Docker。两平台共用 `sparkie.zoom_config` 生成凭证；macOS 原生接收器在 `native/zoom-macos/main.m`。它们只输出音频诊断指标，还没有实现或接入上文的 Python `AudioMeeting`；不能用探针入会成功宣称完整语音闭环完成。

## Zoom 音频桥

`ZoomAudioMeeting` 实现相同 `AudioMeeting` 协议，使用 Linux SDK 7.0.5。Docker 内的 C++ 桥通过只发布到 127.0.0.1 的随机 TCP 端口与宿主 Python 通信。先发送 64 字节随机会话令牌，再交换 `type:1 byte + length:4 bytes big-endian + payload`；每条音频为单声道 PCM16 32 kHz。

SDK → Python：`H` 握手，`M`/`N` 虚拟麦克风可发送/停止，`A` 音频，`S`/`D` 首帧提交/本次音频全部提交（4 字节播放 ID），`E` 固定诊断文本。Python → SDK：`P`（4 字节播放 ID + 最多 30 秒 PCM），`C` 取消播放。单连接、单次播放；两端都有有界队列，溢出或协议错误关闭本轮。C++ 在独立线程中按 20 ms 节奏发送 PCM，音频回调只复制数据，不执行网络 I/O。

`zoom_playback_submitted` 只报告 SDK 首帧接受，不能作为另一参会者的 DAC 时间或可听确认。`zoom-audio` 不设置 `audio_origin` / `last_playback_started_at`，不输出本地设备时延估算。输入在播放及之后 350 ms 替换为静音；这会失去同时发言，也不能在该窗口内靠语音取消。

## Realtime 前台与后台分析（本地验收）

新的唯一网页入口 `/` 使用浏览器 AudioWorklet + `sparkie.realtime_session --transport browser`；`qa` / `wake` 仍可从旧 CLI 启动。
输入 PCM 分成两个独立有界队列：OpenAI Realtime 直接接收音频，Deepgram 只负责最终转写。
Realtime 不等待 Deepgram 的断句，也不等待 Codex 结果。Deepgram 网络失败会记录覆盖缺口，实时对话继续。

`RealtimeAudioTransport`（`audio.py`）使用 PCM16LE、mono、24 kHz：`join` / `audio` / `append_output(item_id, pcm)` / `finish_output(item_id)` / `stop_speaking` / `leave`。
`append_output` 必须立即入有界播放队列；`finish_output` 只标记生成完成，不表示音频已播放。
`outputs` 保存每个 item 的字节数、取消标志和 `played_ms()`；打断会清空待播内容并向 Realtime 发送截断时间，防止未听到的内容留在模型上下文。
本地实现使用 PortAudio DAC 时间估算实际播放进度。Zoom 当前 32 kHz 整段播放协议不满足该接口，需另行实现流式播放、24↔32 kHz 重采样及可靠的播放进度；不能直接声称兼容。

`delegate_task(request)` 立即返回 task_id、queued、awaiting_background 和上下文记录数；`task_status(task_id)` 返回状态和已完成结果；`cancel_task(task_id)` 取消任务。
worker 异步排队执行，提交立即返回；无每会话任务数量上限，也无单任务超时。用户取消或结束会话会终止对应进程。
委派时完整最终转写、生成的助手文本、播放截断标记、覆盖缺口一并快照，不再受旧问答的 50 条限制。
尚未到达的 Deepgram 转写不会伪装成已收集：工具描述要求前台补充当前请求与最近口述；任务记录明确快照截止语义。
完整上下文落盘，路径交给 Codex 读取，不截断到固定提示词长度。按用户授权，Codex CLI 加载用户配置和现有集成，工作目录为实际项目目录，使用 `--dangerously-bypass-approvals-and-sandbox`、`web_search="live"`；可读写文件、执行 shell、研究网页和调用配置的工具。不再传入 ignore-user-config / shell_tool=false / read-only。仅从子进程环境移除语音 OPENAI_API_KEY，以继续复用 CLI 登录；其余工具环境继承。外部服务是否可用仍取决于实际安装与登录状态。

`output/realtime/<session>/transcript.jsonl` 保存全部记录，`tasks.json` 保存任务、不可变输入快照和结果，`events.jsonl` 保存诊断事件，`run.json` 保存会话报告；不保存原始音频。
转写持久化成功后才发送 UI 事件。助手的完整生成文本不代表全部已播放，以 `realtime_interrupted` 为准。
网页默认使用浏览器 `getUserMedia(echoCancellation: {exact: true})`，检查实际 track settings 并将处理后的 PCM 并行发送给两个 provider；不会在 AI 播放时门控人声。浏览器不支持时明确启动失败，不静默退化成无保护双工。旧 local CLI 的扬声器门控仍写入 coverage_gap / coverage_resumed。
结果完成后仅更新界面，不主动打断。用户问进展时用 task_status；点击播报调用 `/api/control` 的 report_task，仅当前语音空闲时执行。
页面只显示对话与任务，诊断事件仍可在日志中查看；`realtime_audio_started.latency_ms` 是最近口述结束到设备首音频的估算，不是后台任务最终答案延迟，也不是独立声学测量。

### Browser audio transport

WebSocket `/audio?session=<id>` 仅接受当前本地 Origin、当前会话和一个连接，PCM 不进入状态轮询或磁盘日志。browser→Python：audio_settings、连续 sequence 的 audio_input、带 generation 的 audio_progress。Python→browser：audio_ready、audio_output、audio_clear。只有 provider ready 后才发输入；24 kHz PCM16 mono、20 ms 包；队列/管道溢出明确失败。清空播放递增 generation，旧音频/播放进度不能复活。AudioWorklet 每 20 ms 报告渲染进度供截断使用，不宣称是准确 DAC 时间。密钥仍仅保存在 Python。浏览器断开关闭会话并释放麦克风。

Realtime 工具回调立即回传 queued，后台不阻塞音频事件循环；工具续答使用 response_pending 避免重复 response.create，用户发言期间不抢建回复。前台对外部信息、网页、文件、代码和外部工具请求应直接委派，而不是建议用户自己完成或声称没有工具。
