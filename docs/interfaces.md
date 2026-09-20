# Phase 0 接口约定

## macOS Zoom 分轨语音打断（当前行为）

本节覆盖下文旧混音前台的打断限制，仅适用于支持 dual-input-v1 的 macOS Realtime 会话。Linux、browser/local 和 legacy wake/qa 保留既有输入路径。

- 原生 U 音轨排除 SDK 自身 userID；ParticipantEars 再按 is_self 过滤。播放期间继续读取各真人音轨，不使用全局播放静音门控。
- Deepgram 请求 vad_events=true。共享 SpeechActivity(phase, timestamp_ms, speaker_id, stream_id) 区分 candidate / started / stopped：原始 SpeechStarted 只发 candidate，首个包含文字的 interim 或 final 才发 started；不等待整句最终转写，也不把无文字 VAD 直接视为真人打断。首次连接与识别延迟仍影响正式停止时间。
- SpeechActivity 与 TranscriptEvent 经同一有界队列按每条连接的顺序送入 RealtimeAgent。candidate 在当前输出链上开启固定 350ms 确认窗口，暂停后续 100ms 音频包的提交，保留模型回复和待播 PCM；当前已提交的包正常完成以避免续播重复/丢样。重复 candidate 不延长窗口。窗口内 started 才正式取消生成、清空播放并沿用 cancel-v1 与语义截断；否则从保留的剩余 PCM 继续播放，不重新生成。晚到的 started 仍会正式打断已恢复的输出。明确 mute/stop、输入失败和退出取消恢复定时器。speech_final / UtteranceEnd 或连接正常结束释放 speaking；重复 final 及同段 interim 回放不能再次打断。
- 使用分轨最终文本作为 Realtime 的权威用户输入，包括普通讨论与播放期间的发言。原 A 混音流保留采集时钟，但发给 Realtime 的 PCM 全部置零；不把混音和分轨文本当成两轮输入。输入模式由会话启动时确定，不调用人工 human_turn 切换，不依赖前台混音 VAD。前台因此等待 Deepgram 最终文本，不再直接理解该模式的原始声学输入。
- 确认人声停止当前输出，但普通讨论不自动授权新回复；最终文本仍要求 Sparkie/Sparky 显式唤醒。仅短的明确静音指令（stop / stop speaking / never mind / cancel 等）关闭自动输出；带唤醒的 cancel the task / stop the server 交给 agent 处理。mute 立即取消当前输出并暂停自动结果播报；unmute 只保留给下一轮最终文本，后台通知不能抢占。新回答等待所有确认发言的音轨结束及旧 response.done；正式取消后不续播旧 PCM。
- 打断不取消后台工作，也不等于永久静音。通知循环每 100ms 重新检查 pending 结果，不依赖一次性的完成队列事件；确认人声打断的结果在发言结束、至少 750ms 安静且输出空闲时重新生成报告，已 offered/confirmed 的结果不自动重复。只有明确 mute/stop 或输入失败暂停自动报告；新的显式唤醒或可信 report_task 可以解除相应的静音状态。分轨识别失败时停止当前输出，保持 Realtime 连接和后台任务，记录 zoom_barge_in_unavailable 与转写覆盖缺口；不会静默降级为可能自打断的混音。恢复自动语音需重启会话；可信 human_turn 手动文本控制仍可用。

诊断：zoom_speech_candidate / zoom_barge_in_pending / zoom_barge_in_false_alarm 记录疑似声音、350ms 暂停和保留音频的恢复；zoom_human_speech_started / zoom_human_speech_stopped 含 speaker_id、stream_id；开始事件在本地/native 取消之前发出，其 elapsed_ms 表示应用收到语音事件，不是远端听到停止的时刻。transcription_config.foreground_input=participant_final_text、barge_in=participant_interim_text。分轨 ID 排除机器人自身音轨，不能排除他人麦克风重新录入的扬声器回声，也不能区分共用同一 Zoom 端的多人。

离线测试覆盖真实适配器间的事件/状态闭环，不代表真实 Zoom 会议验收或远端可听延迟已通过。启动和真人验收见 docs/realtime.md 的“分轨打断验收”。

## 本地双人讨论转写测试页

当前 /multitrack.html 使用两个互斥的麦克风按钮，将同一真实麦克风路由到两个模拟参会者；点击当前按钮可全部静音。两路共用 32 kHz AudioWorklet 时钟，每 20 ms 发送当前参与者 PCM 与另一条零填充音轨。切换时清除旧部分帧，主线程按 capture epoch 拒绝切换前排队的语音，避免跨身份串音。页面只调用真实 Deepgram，不加入 Zoom、不调用 Realtime 或后台任务。

同源 WebSocket /multitrack-audio 启动独立 Python sparkie.multitrack_lab 子进程。首条 start 含 language 和 tracks（协议支持 2–4 个 {name}，当前 UI 固定两个）；随后 frame 含从零连续递增的 sequence 和同顺序 tracks 数组，每项为 1280 bytes 的 base64 PCM16 mono 32 kHz。统一时间为 sequence × 20 ms；分轨帧使用生产 U 解码/队列及 ParticipantEars，零帧不打开识别连接。finish 排空队列并等待最终转写。

输出 ready、participant_stt_ready/closed、progress、transcript、completed/failed；转写包含 speaker_id、speaker、timestamp_ms、event_id。会话持续到手动结束，不再限制 60 秒音频或 95 秒连接；初始化等待 20 秒、输入空闲 15 秒、最终转写等待 15 秒及缓存上限仍有效。结束时先关闭麦克风再等待最终文本；关闭页面直接释放本轮连接。详情与实际验证见 [双人讨论测试页](multitrack-lab.md)。

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

任务层使用独立异步 worker。Realtime 会把完成或失败通知入队，在当前用户轮次和音频播放结束后唤醒前台，由前台决定播报或 remain_silent。demo.py 尚未实现 worker。

## 会议报告

至少包含 meeting_id、标题、时间、参与者、overview、key_discussion_points、decisions、action_items、open_questions、tasks、transcript。action item 格式：`{text, owner: null|string, deadline: null|string, evidence_event_ids: string[]}`。owner 和 deadline 仅在 transcript 明确提及时填写。决策及行动项应可追溯到原始事件。

离线 harness 只产出最小回放包，完整报告元数据、摘要与页面由当轮编码负责人实现。模拟产物必须保留 `mode: mock`。真实报告禁止沿用固定内容冒充模型结果。

## Zoom 独立接收探针

`scripts/zoom-sanity.py` 通过 `--platform linux|macos` 或 `ZOOM_PLATFORM` 选择运行时，默认保留 Linux Docker。两平台共用 `sparkie.zoom_config` 生成凭证；macOS 原生接收器在 `native/zoom-macos/main.m`。探针模式（无 `voice` 配置）只输出音频诊断指标；macOS 接收器另有 voice 模式实现下方音频桥协议并接入 `AudioMeeting`，其实际会议语音验收尚未完成，不能用入会成功宣称完整语音闭环。

## Zoom 音频桥

`ZoomAudioMeeting` 实现相同 `AudioMeeting` 协议，使用 Linux SDK 7.0.5；`ZoomMacAudioMeeting` 复用同一协议，由原生 macOS 应用承载 SDK（7.1.5 基线）。Docker 内的 C++ 桥通过只发布到 127.0.0.1 的随机 TCP 端口与宿主 Python 通信；macOS 应用直接绑定 127.0.0.1 的每轮随机端口，令牌经权限 600 的 config.json 传入。先发送 64 字节随机会话令牌，再交换 `type:1 byte + length:4 bytes big-endian + payload`；每条音频为单声道 PCM16 32 kHz。

SDK → Python：`H` 握手，`M`/`N` 虚拟麦克风可发送/停止，`A` 音频，`S`/`D` 首帧提交/本次音频全部提交（4 字节播放 ID），`E` 固定诊断文本。Python → SDK：`P`（4 字节播放 ID + 最多 30 秒 PCM），`C` 取消播放。单连接、单次播放；两端都有有界队列，溢出或协议错误关闭本轮。C++ 在独立线程中按 20 ms 节奏发送 PCM，音频回调只复制数据，不执行网络 I/O。

取消协议：Linux H payload 为 ASCII cancel-v1；macOS 更新为 cancel-v1,dual-input-v1，包含双路输入能力。`C` 现在携带 4-byte big-endian 单调递增取消 ID；原生 `K` 回传同一 ID，只有旧 generation 的 SDK send/sleep 已结束、待播包已清空后才确认。Python 序列化 C 与新的 P，最多等 5 秒（包括发送时间）；旧 ID 不解除等待。超时、断连或取消等待被中断会禁用该连接，不能继续提交替代音频。原生网络线程不等待 SDK，不在持有 sender mutex 时等待取消；播放线程在空闲边界发 K。旧空 H / 无确认 C 不做兼容降级，启动明确提示重建 macOS receiver 或 Linux image。诊断 reason 包含 bridge_rebuild_required、cancel_ack_timeout、cancel_aborted。

macOS `E` 现在为版本 1 JSON：`reason` 只允许 `sdk_send_failed` / `playback_active` / `microphone_unavailable` / `invalid_input_format`，另带整数 `sdk_result`、`playback_id`、`frame_index`（从 1 开始的发送尝试；无尝试为 0）。`sdk_result=-1` 表示未调用 SDK，没有实际返回码。原生日志保留相同 `BRIDGE_ERROR`。Python 兼容上述四种旧固定文本，未知内容只记 `unknown_native_error`，额外字段和任意正文不会进入遥测。`ZoomBridgeError` 的白名单字段进入 `audio_failed`、`session_failed` 和 `run.json.failure`；错误仍终止本轮，不盲目重试 SDK 发送。

`zoom_playback_submitted` 只报告 SDK 首帧接受，不能作为另一参会者的 DAC 时间或可听确认。`zoom-audio` 不设置 `audio_origin` / `last_playback_started_at`，不输出本地设备时延估算。Linux 混音输入在播放及之后 350 ms 替换为静音；这会失去同时发言，也不能在该窗口内靠语音取消。macOS 分用户路径见下文。

### macOS Zoom Realtime 分用户转写（SDK 7.1.5）

RealtimeZoomAudio 在入会前选择 participant_audio=true、mixed_audio=true。原生桥同时发送 A 连续混音与 U 分用户音频；Python 为两者使用独立有界队列。A 进入 32→24 kHz 重采样以保留前台输入时钟，当前分轨模式发送给 Realtime 前会置零；U 进入 ParticipantEars 与独立 Deepgram 连接，提供前台 VAD 边界和最终文本。两者不能拼接，U 也不会再复制到混音转写队列。Linux 和浏览器保持原有转写链路。wake/qa 为 legacy，保留其原有独立模式。

macOS H 握手必须是 ASCII cancel-v1,dual-input-v1；旧二进制会明确提示重建。Linux 仍使用 cancel-v1。既有取消确认协议保持不变。

- A：混音 PCM16 mono 32 kHz，前台继续保留播放/尾音门控。
- U：userID（4 字节 BE）+ 帧起始 timestamp_ms（8 字节 BE）+ PCM16 mono 32 kHz，总 payload 不超过 64000 字节；过滤 SDK 自身 ID，不做全局播放门控。
- J：JSON 参会端列表，含 user_id、name、is_self；主线程每秒检查变化，音频回调不查名字、不做网络 I/O。
- R：空 payload 健康心跳，静默会议也能就绪。

AudioFrame 携带可选 speaker_id、timestamp_ms；优先使用归一化 SDK getTimeStamp，缺失时用单调回调时间减帧长估计，不是精确声学时间。TranscriptEvent 的 speaker_id 为 zoom:<userID>，speaker 为显示名或 ID；同名参会端不合并。

ParticipantEars 按用户分流，每条连接独立断句。仅非零 PCM 建立/续期连接，1.5 秒无非零帧后补 500 ms 静音并关闭；之后发言开启新段，事件 ID 带用户和段编号。段内空隙补静音，长停顿按新会议时间偏移处理。噪声可能保持连接，这不是语义 VAD。默认并发上限 32（含结束中的连接），SPARKIE_ZOOM_MAX_STT_STREAMS 可设为 1–64。

Realtime 的分轨入口队列最多 500 帧，每条转写连接也最多 500 帧。分轨队列、并发超限或提供者失败会停止本轮分轨转写并记录 transcript_degraded / coverage_gap；后续 U 丢弃，前台连接和后台任务仍继续，但自动语音输出关闭。桥断线或协议错误则终止整个会话。前台混音门控只记 realtime_input_coverage，不伪造分轨转写缺口。

积压输入使用 get_nowait 优先排空，空队列才进入带超时的等待；分流器每路由 32 帧主动让出执行。避免桥接收器批量读入 A/U 时，分流器逐帧让出导致入口队列被调度差异填满。保留原有容量与显式超限行为，不靠扩大队列掩盖慢消费者。

启动 transcript_ready 的 readiness=router 仅表示分流器可接收；每位用户的真实连接就绪单独记录 participant_stt_ready。结束时先停止分轨输入、排空并刷新转写，最多等 10 秒，超时记录缺口，然后关闭所有连接。transcript.jsonl 按结果到达顺序保存，后台快照保留身份与时间；run.json 的 transcript 按 timestamp_ms 排序。

同一 Zoom 端共用麦克风不能分人；远端声学回声可能进入分轨 STT。当前前台通过独立分轨 VAD 打断，不依赖混音门控。离线或合成输入验证不作为真实多人会议成功证据。

## Realtime 前台与后台分析（本地验收）

新的唯一网页入口 `/` 使用浏览器 AudioWorklet + `sparkie.realtime_session --transport browser`；`qa` / `wake` 仍可从旧 CLI 启动。
输入 PCM 分成两个独立有界队列：OpenAI Realtime 直接接收音频，Deepgram 只负责最终转写。
Realtime 不等待 Deepgram 的断句，也不等待 Codex 结果。Deepgram 网络失败会记录覆盖缺口，实时对话继续。

本地语音默认浏览器 autoGainControl=false、echoCancellation=true、noiseSuppression=true；Realtime input.noise_reduction=far_field，server_vad threshold=0.5、prefix_padding_ms=600、silence_duration_ms=600，create_response=false，由应用在输入提交后创建回复；本地/浏览器保留 interrupt_response=true，Zoom 使用下方输出策略。realtime_ready 记录服务端返回的实际 noise_reduction 和 turn_detection。无清晰语音时可调用 remain_silent，不据此伪造用户说过的话；该工具统一记录 realtime_silent，替代原本仅表示后台通知延后汇报的 background_notification_deferred。

`RealtimeAudioTransport`（`audio.py`）使用 PCM16LE、mono、24 kHz：`join` / `audio` / `append_output(item_id, pcm)` / `finish_output(item_id)` / `stop_speaking` / `leave`。
`append_output` 必须立即入有界播放队列；`finish_output` 只标记生成完成，不表示音频已播放。
`outputs` 保存每个 item 的字节数、取消标志和 `played_ms()`；打断会清空待播内容并向 Realtime 发送截断时间，防止未听到的内容留在模型上下文。
本地实现使用 PortAudio DAC 时间估算实际播放进度。Zoom 由 `RealtimeZoomAudio` 适配：SoXR 有状态重采样 32↔24 kHz，输出累计到 100ms 就通过既有原生协议提交，最后一块在生成结束时 flush，不等待整句。`played_ms()` 只累计已完成 SDK 提交的包；打断时不计尚未确认的包，是保守进度，不是远端 DAC 或可听证明。

`delegate_task(request)` 立即返回 task_id、queued、awaiting_background 和上下文记录数；`task_status(task_id)` 返回状态和已完成结果；`cancel_task(task_id)` 取消任务。
`update_task(task_id, request)` 接收完整修订请求并刷新快照，保持任务 ID。queued 任务保留队列位置；running 的 Devin 任务通过队列传递修订，ACP 中断当前轮后在同一会话继续。返回 update_delivery=pending 不能宣称已执行；applied_revision 和 delivered 表示已送入后台连接。request_history 保存历史请求，连续修订以最新完整请求为准。其他 running 后端及 completed 任务拒绝更新，已发生的操作不会回滚。
worker 异步排队执行，提交立即返回；无每会话任务数量上限，也无单任务超时。取消 Codex 任务会终止对应进程；取消 Devin 当前轮保留常驻会话，结束语音会话会终止进程组。
`task_workers.py` 选择独立 Codex / Devin 适配器，Devin 协议实现位于 `devin_acp.py`。共用 `run(request, transcript)` / `run_with_progress(request, transcript, progress)`；持久 worker 另提供 start / close，支持运行中修订时通过 updates 队列接收 `(request, snapshot, revision)`，initial_revision 表示开始运行时的修订号。`SPARKIE_TASK_BACKEND=codex|devin` 选择 Realtime 后台及 workspace 默认 worker；显式 --worker 优先，未配置时默认 codex；DEVIN_MODEL 默认 swe-1-6-fast。前台语音及旧 Q&A SPARKIE_BACKEND 不变。

Devin 每次语音会话启动一个 `devin acp --model ...` 进程，经 initialize / session/new / session/set_mode 建立无审批会话；后续串行发送 session/prompt，共享历史。session/update 仅提取公开回答和工具类型/状态，忽略思考内容及原始工具输出；session/request_permission 复用已有用户授权，仅选择当前会话的 allow_once 选项。取消用 session/cancel，5 秒无应答则杀进程组；连接断开、RPC 错误、非 end_turn、空结果均不能作成功。进程断开不自动重启或重放任务，避免重复外部操作及丢失上下文。取消确认期限和 60 秒启动期限不是任务超时。

会话发出 task_backend_config、task_backend_starting / task_backend_ready / task_backend_failed。运行任务包含 backend/model、agent_session_id、agent_pid、revision/applied_revision 和 update_delivery。常驻进程在项目目录继承 CLI 登录与工具配置，移除语音 OPENAI_API_KEY。完整快照的临时文件存续到语音会话结束；TaskCenter.close 终止进程并清理临时目录，新语音会话不继承旧 ACP 上下文。
委派时完整最终转写、生成的助手文本、播放截断标记、覆盖缺口一并快照，不再受旧问答的 50 条限制。
尚未到达的 Deepgram 转写不会伪装成已收集：工具描述要求前台补充当前请求与最近口述；任务记录明确快照截止语义。
完整上下文落盘，路径交给 Codex 读取，不截断到固定提示词长度。按用户授权，Codex CLI 加载用户配置和现有集成，工作目录为实际项目目录，使用 `--dangerously-bypass-approvals-and-sandbox`、`web_search="live"`；可读写文件、执行 shell、研究网页和调用配置的工具。不再传入 ignore-user-config / shell_tool=false / read-only。仅从子进程环境移除语音 OPENAI_API_KEY，以继续复用 CLI 登录；其余工具环境继承。外部服务是否可用仍取决于实际安装与登录状态。

`output/realtime/<session>/transcript.jsonl` 保存全部记录，`tasks.json` 保存任务、执行时的输入快照和结果，`events.jsonl` 保存诊断事件，`run.json` 保存会话报告；不保存原始音频。Codex JSON 事件只提取执行步骤与用量元数据作为 progress，不把原始命令输出或 stderr 转发到前端。
转写持久化成功后才发送 UI 事件。助手的完整生成文本不代表全部已播放，以 `realtime_interrupted` 为准。
网页默认使用浏览器 `getUserMedia(echoCancellation: {exact: true})`，检查实际 track settings 并将处理后的 PCM 并行发送给两个 provider；不会在 AI 播放时门控人声。浏览器不支持时明确启动失败，不静默退化成无保护双工。旧 local CLI 的扬声器门控仍写入 coverage_gap / coverage_resumed。
结果完成或失败后更新界面，同时向 Realtime 投递包含任务结果的系统通知并触发 response.create。任务通知使用下方持久化 announcement 状态，忙碌期间排队，多个完成结果合并唤醒；等待用户轮次与全部本地音频播放结束。前台自行决定直接汇报或调用 remain_silent（不生成后续语音），结果保留在对话上下文。用户问进展仍可用 task_status；手动 report_task 仍只在空闲时执行。通知循环随会话关闭取消；断开后不跨会话自动重投。
页面只显示对话与任务，诊断事件仍可在日志中查看；`realtime_audio_started.latency_ms` 是最近口述结束到设备首音频的估算，不是后台任务最终答案延迟，也不是独立声学测量。

### Browser audio transport

WebSocket `/audio?session=<id>` 仅接受通过本机网络接口地址的同源 Origin、当前会话和一个连接，PCM 不进入状态轮询或磁盘日志。browser→Python：audio_settings、连续 sequence 的 audio_input、带 generation 的 audio_progress。Python→browser：audio_ready、audio_output、audio_clear。只有 provider ready 后才发输入；24 kHz PCM16 mono、20 ms 包；队列/管道溢出明确失败。清空播放递增 generation，旧音频/播放进度不能复活。AudioWorklet 每 20 ms 报告渲染进度供截断使用，不宣称是准确 DAC 时间。密钥仍仅保存在 Python。浏览器断开关闭会话并释放麦克风。

Realtime 工具回调立即回传 queued，后台不阻塞音频事件循环；工具续答使用 response_pending 避免重复 response.create，用户发言期间不抢建回复。前台对外部信息、网页检索、文件/代码和外部工具请求统一委派，包括创建桌面文件和打开网页或本地报告。前台仅保留 delegate_task、task_status、update_task、cancel_task 和 remain_silent 五个工具，本机快捷执行分支已移除。

浏览器 `seconds=0` 表示手动结束；限时模式支持 1–3600 秒。浏览器输入包续期页面及音频心跳，输入停顿只提示恢复麦克风，不取消后台任务；关闭页面、断开音频 WebSocket 或显式结束仍终止会话。`browser_audio_settings` 包含 AudioContext 和 track 状态，供排查暂停/设备中断。

Realtime 的 Deepgram 适配器可通过 on_partial 回调发出 `transcript_partial`。网页服务将其合并为 `partialTranscript` 状态，显示“正在转写”，不加入最终事件历史、持久转写或任务上下文。最终 transcript 或连接结束清空预览。识别修订可替换预览，只有最终 transcript 可作为任务依据。

`audio_input_diagnostics` 每累计两秒输入记录一次 RMS dBFS、峰值、削波比例、全零采样比例和最大包间隔；只保存统计，不保存音频。browser_audio_settings 另含实际设备标签、autoGainControl 和 trackEnabled。页面显示是否正在接收声音，并在 15 秒内两次回复被取消时给出暂时提示；该提示不能证明是回声或噪声，也不改变自动打断行为。
### Zoom Realtime 会话

`bash scripts/zoom.sh` 默认 `--response-mode realtime`，复用同一 `RealtimeAgent`、`TaskCenter` 和所选 Codex / Devin worker。输入并行送 GPT Realtime 与 Deepgram；回复直接使用 Realtime 输出音频，不经过 Deepgram TTS。`wake` / `qa` 仅在显式指定时进入旧 primitive。也可直接用 `python -m sparkie.realtime_session --transport zoom`。

`RealtimeZoomAudio.append_output` 只进行有状态重采样和有界入队（所有 item 合计最多 120 秒待播 PCM，7,680,000 bytes，包含最多一个尚未确认的 100ms 在途包）；独立异步播放任务按 100ms 包复用 Zoom 原生桥的 20ms 发送节奏。保留 item_id、取消状态与生成/SDK 提交进度；取消清除尚未发送的内容，迟到的相同 item 音频不会恢复播放；后台结果通知等待待播语音处理完毕。SDK 错误会结束输入并报告失败。

Zoom 播放队列或单条回复时长达到上限时，`PlaybackLimitError` 由 Realtime adapter 捕获：记录 `realtime_playback_limited`，取消当前回复并按已确认的 SDK 播放进度截断上下文；清空待播音频，继续接收后续会话，不扩大队列。该回复可能只播放一部分。`session_failed` 和 `run.json.failure` 保存 `error_type`、`provider`、本地白名单 `reason`、可用的代码位置 `source` 和白名单 `provider_code`；未知原因标为 `unclassified`，不保存异常正文、provider message、响应 body 或凭据。

输入仍受原生 Zoom 播放期间及尾音 350ms 的回声静音窗口限制，并向 transcript ledger 记录 `zoom_echo_gate` 覆盖缺口。这个传输没有浏览器 AEC，尚不支持在回复期间靠语音打断；stdin `{"action":"interrupt"}` 控制可以取消。会话退出会停止原生进程/容器和后台任务。所有 Zoom 播放指标均明确为 SDK 提交进度，不报告声学延迟。真实 Realtime + Codex 会议验收仍待完成。


### Zoom Realtime duration and capture gating

Zoom Realtime accepts 1–3600 seconds. Listening readiness records configured_duration_seconds and duration_deadline_elapsed_ms; the limit starts after joining. Normal expiry emits session_duration_elapsed and saves exit_reason=duration_elapsed with exit code 0. Signals remain stopped; failures remain failed. Duration expiry ends playback too; use --seconds 3600 for conversation runs.

AudioFrame has an optional gated field (default None). Zoom freezes the gate decision when an A frame enters Python, before the bounded input queue, and replaces gated PCM with equal-length zeros. This is bridge-receive timing, not a remote capture timestamp: mixed A packets have no capture clock. Native callback gating still covers SDK playback and its tail before native/network backlog. The Python gate additionally spans pending output, generation gaps, SDK stalls, and 350ms after playback/cancellation. A queued gated frame cannot become audible merely because consumption occurs later. Resampling maps gated intervals by sample counts; output chunks overlapping an interval are conservatively zeroed in full, and the same frames/coverage markers reach both providers. Chunk-level suppression can slightly extend the gap; sample count and cadence are preserved. No speaker-mode voice barge-in or full-duplex AEC is claimed.

The aggregate 120-second playback queue remains bounded across multiple items, and each item retains the hard 120-second generation limit. Overlapping items whose combined pending audio exceeds that aggregate limit still fail explicitly and invoke cancellation; interruption reclaims all pending PCM and resamplers. Realtime Zoom limits routine zoom_playback_submitted telemetry to once every five seconds, retaining per-item first submission and all errors/completion acknowledgements.

Idle speech_started does not create or extend a silence window. Cancellation adds the 350ms echo tail only when output is active, pending or in flight; an existing genuine playback tail retains its original deadline when idle. Replacement playback waits for native cancellation acknowledgement, including cancellation triggered by stopping an in-flight Python play task.

### Semantic interruption and trusted human controls

Interruption cancels the active response and any response.create already in flight, stops **all** transport outputs through the existing cancel-v1 barrier, discards pending PCM/resampler state, and truncates every incomplete assistant audio item at the transport's conservative progress estimate. Late chunks for cancelled responses, including previously unseen items, cannot restart playback. Cancelled items are truncated once. Generated transcript fragments are retained as explicitly unconfirmed draft context, separate from heard conversation; verified task results remain the source of truth. No native protocol changes are required.

The application now owns response creation: server VAD still detects speech and cancels generation, but create_response=false. Speech-start cancels playback; speech-stop alone does not regenerate. The subsequent input_audio_buffer.committed event makes the user audio turn available. Fresh response creation waits for any cancelled response to finish, injects pending semantics, and generates new audio. The same ordering applies to an externally committed text turn. A terminal interrupt with no subsequent turn deliberately stays silent; it never resumes old PCM.

TaskCenter persists an announcement object in tasks.json, independent of job execution status:

- pending: completion/failure awaiting a response opportunity, ordered by completion.
- offered: result supplied to Realtime for an attempt; generation, queueing, rendering and SDK submission do **not** confirm delivery.
- confirmed: a trusted explicit human acknowledgement of that task and attempt. Confirmed results are excluded from automatic recovery and the model receives a do-not-repeat update. A user can still explicitly request a result again.

Interrupting an in-flight announcement or one with unfinished playback returns its unconfirmed tasks to pending in original order. Repeated interruptions deduplicate obligations. Tool continuations retain their associated announcements. Results offered in an uninterrupted, fully submitted reply remain offered/unconfirmed: ordinary later speech does not automatically repeat them. remain_silent likewise leaves results available without an automatic notification loop. Pending results are explicitly supplied for reconsideration after the new user turn; fresh wording and whether to defer depend on that turn. This is delivery uncertainty, not a claim of audibility. Tasks and announcement states persist for inspection; automatic cross-session recovery remains unsupported.

background_notification_offered replaces the misleading background_notification_delivered event and includes announcements [{task_id, attempt}] plus delivery_confirmed=false. background_notification_confirmed is emitted only on explicit human confirmation. Attempt IDs reject stale confirmations after retry. Cancellation, native errors and truncation diagnostics remain intact.

Trusted stdin JSON controls (also callable as RealtimeAgent.control from a local integration):

~~~json
{"action":"interrupt"}
{"action":"human_turn","source":"human","turn_id":"human-42","phase":"start"}
{"action":"human_turn","source":"human","turn_id":"human-42","phase":"commit","text":"Stop; just give me the conclusion."}
{"action":"confirm_delivery","source":"human","task_id":"<task-id>","attempt":1}
~~~

human_turn start stops playback immediately, before provider cancellation/truncation messages. A matching commit supplies authoritative final human text (nonempty, at most 8000 characters), records it in the transcript ledger and requests fresh generation. IDs are unique per session, 1–128 characters; duplicate starts/commits are idempotent. Only one external turn may be open; another start or unmatched commit is rejected. source=bot or missing source is rejected. These labels are a trusted caller contract, **not speaker identification or authentication**. The teammate's separator must exclude Sparkie's output before calling this boundary; this module performs no separation, diarization, VAD or STT on separate streams.

The first human_turn start selects external-text input for the remainder of that session. Mixed microphone frames sent to Realtime become equal-length silence, and mixed VAD commits are removed/ignored, including delayed events, so a turn cannot appear through two input paths. All subsequent conversational turns must use start/commit controls; restart the session to return to mixed audio input. Deepgram's existing capture/transcription path and capture-time Zoom echo gate are unchanged; externally committed text is separately recorded as source=human. The legacy interrupt control alone does not select external-text mode and can still be followed by a normal microphone turn once the echo tail expires.

Zoom speaker mode still cannot acoustically hear an interruption through its gated mixed input. The external signal can stop playback immediately when received; already submitted SDK/network/device audio cannot be recalled, and cancel-v1 acknowledgement does not establish the remote stop instant. Real meeting testing must verify acoustic stop latency, response sequencing and natural semantic recovery. No remote audibility or full-duplex capability is claimed by offline tests.

Interruption review refinements: public response requests acquire the same turn lock as controls, provider events and notifications; internal transitions use a separate lock-held helper (no recursive lock acquisition). Announcement deferral matches both task_id and attempt, including explicit report_task retries and send failures. Completion during a semantics send remains independently pending. Duplicate response-created/done and microphone-start/commit events cannot consume newer state. An overlap error restores pending obligations and waits for the existing response before retrying. An unsolicited cancellation clears queued playback even if its speech-start event has not arrived yet.

Cancelled audio cleanup records the provider content_index and also tracks audio-transcript parts with no PCM delta. Late final transcripts update draft context; identical final/delta replays do not enqueue already supplied text again. Only audio content is truncated; committed mixed-input items are deleted once; cancelled function calls receive one explicit non-executed output without running tools. Local playback progress freezes at cancellation while queued PCM is reclaimed. Simple injected task stubs remain usable: notification obligations are retained in memory when persistence methods are absent, and unsupported delivery confirmations are rejected rather than crashing. These protocol paths are tested offline; provider acceptance and remote playout timing still require live validation.

### Zoom output mute MVP (supersedes automatic replies for all Zoom turns)

Zoom final-transcript matching also checks explicit sentence starts within an aggregated final segment: after 。！？!? or a period followed by whitespace/end. Only the observed compact greeting helloSparkie/helloSparky (case-insensitive, with the existing exact name boundary) gains a missing space before applying wake.py rules. Commas, mid-sentence name mentions and speculative transliterations do not become wakes. The last explicit addressed wake/cancel in a segment wins; an unaddressed cancel is recognized only at the original segment start. The selected addressed suffix is supplied as the fresh request; preceding discussion remains in the live audio context. This normalization is Zoom-only; shared wake.py and browser/local behavior are unchanged.

Diagnostics: zoom_wake_decision contains fixed decision/reason, sentence_index and compact_greeting_normalized, never transcript text. zoom_response_not_requested distinguishes wake_rejected, explicit_mute, output_muted and waiting_for_turn_or_response (with state booleans). zoom_response_requested is emitted after response.create is sent; it is not provider acceptance or audibility. Existing realtime_response_started and zoom_output_suppressed distinguish provider response creation and rejected PCM. Duplicate final transcripts still cannot request twice.

Zoom Realtime sessions install a local ZoomOutputPolicy and begin output-muted. This is Python output routing, not Zoom platform microphone toggling or input mute. PCM input, Deepgram, the same foreground Realtime connection/conversation and Codex jobs continue. No reconnection/context rebuild occurs on wake. Browser/local sessions do not install this policy and retain their existing behavior.

create_response remains false. While output-muted, ordinary committed audio stays in the Realtime conversation but does not request an assistant response. This avoids creating unheard assistant answers without losing incoming meeting context. Deepgram final human transcripts apply the exact existing wake.py sentence-start Sparkie/Sparky rules (optional Hi/Hey/Hello, existing ASR special case); partial/bot/duplicate records cannot open output. Cancellation uses existing CANCEL rules, with or without a leading address; no model classifier or new fuzzy phrases. The addressed final text is additionally inserted as the explicit request before response.create because the two providers do not share turn IDs. That can duplicate the textual representation of already heard audio, but never creates a second response from the audio commit. ASR segmentation/latency and sentence-start product-name false wakes retain their existing limitations.

Zoom mixed-input VAD no longer automatically interrupts responses (interrupt_response=false, Zoom only), preventing late events for the same utterance from cancelling its newly authorized answer. Final cancellation text, terminal controls and trusted human_turn/start still cancel. A different qualifying addressed final transcript supersedes the previous chain. Unrelated speech does not authorize another response or extend output permission. Deepgram failure therefore disables automatic transcript wake; the live Realtime input continues, and manual unmute plus trusted human_turn controls remain available.

The output permit belongs to a response chain, including its legitimate tool continuations and all queued items. It closes only after the terminal response.done and queue drain/cancellation. Late or unsolicited responses cannot reuse a permit: unowned audio is suppressed before resampling/enqueue, tracked as unheard draft content and truncated through existing semantic-interruption mechanisms. The transport independently checks item ownership. zoom_output_state / zoom_output_control / zoom_output_suppressed are concise diagnostics, never remote-audibility evidence.

There is no product speech-duration limit and Zoom's former per-item 120-second generation limit is removed. The aggregate bounded pending-PCM capacity remains 120 seconds (7,680,000 bytes including the unacknowledged in-flight packet); it is a backlog safety limit, not a maximum total reply duration. Overflow still fails explicitly/cancels rather than dropping audio or growing unbounded. Long replies drain normally while generation continues. Configured overall session expiry also remains in force.

Tasks created by an authorized response chain (delegate_task) receive zoom_output_origin=addressed_turn in tasks.json and an in-session eligibility record. Only their pending notification attempts may open output at the existing idle opportunity; unrelated task completions remain pending/visible and cannot open output or be automatically mixed into offered semantics. Mute/interruption returns affected offers to pending without cancelling jobs or marking them delivered. Confirmed states remain unchanged. Automatic reannouncement pauses only after explicit dismissal/manual mute until a new wake; ordinary participant interruption remains pending and is retried when quiet; pending information is reconsidered on that new chain or an explicit eligible report_task. Eligibility is not restored as an output permit after restart.

Trusted controls: {"action":"mute"} immediately revokes the current chain and stops/clears all queued audio through semantic interruption and cancel-v1; jobs and input continue. {"action":"unmute"} also clears/revokes any stale chain and arms the **next final human turn**, even without a wake name; it does not replay PCM, immediately speak, or enable all future turns. A wake name can reopen output after mute; mute is not a permanent hard lock. In external-human mode, final human_turn text uses the same rules; start still stops current playback. Speaker separation is not implemented. Existing external-text input selection remains an independent input mode, never a consequence of mute/unmute.

Restart/new sessions always start output-muted with no restored chain. There is currently no automatic reconnect in RealtimeAgent; a replacement session must construct a fresh policy. Zoom's existing speaker echo gate still hides mixed human speech during audible playback plus its tail; acoustic stop phrases in that window require the separated-human control producer. Native protocol/build is unchanged, and already submitted remote audio cannot be recalled.

### Bounded Zoom join and macOS native startup diagnostics

Python owns an absolute join_timeout (default 120 seconds), now covering launch, bridge handshake and audio/microphone readiness. A watchdog observes startup even when the bridge handshake itself blocks. No automatic join retry is performed. Success still requires both received audio and microphone readiness, not JOIN_REQUEST result=0 or AudioReady alone.

The macOS receiver joins muted, installs the external microphone, then requests unmute, restoring the pre-multitrack startup sequence. An already-unmuted SDK state is not proof that the external source received onMicStartSend. There is no automatic re-unmute loop. Until join succeeds, both A and U input frames are discarded before entering their consumer queues; zoom_startup_audio_discarded explicitly marks this startup coverage gap and audio diagnostics count startup_frames_discarded. Participant metadata and readiness/control packets continue to be processed. Startup speech cannot trigger an unplayable reply, and a missing mic callback reaches the existing bounded audio_readiness_timeout instead of QueueFull. Speak only after listening_ready; after that, normal bounded queues and overflow failures remain unchanged.

The installed macOS receiver already writes fixed startup/status records to its private sdk.log. Python incrementally reads only full allowlisted records (bounded reads and line buffers); no SDK rebuild or protocol change is needed. zoom_join_progress preserves native_stage/sdk_result and, when available, meeting_state, meeting_state_name, meeting_error, meeting_end_reason, state_observed_ms plus fixed actionable hints. Raw SDK lines, arbitrary error text, config values and credentials are never copied into events/run.json. These are macOS SDK 7.1.5 enum values; 1/101 is Connecting/no error, not an immediate failure. State 2 is WaitingForHost and 10 is InWaitingRoom.

At the overall deadline zoom_join_failed distinguishes connecting_timeout, waiting_for_host_timeout, waiting_room_timeout, audio_readiness_timeout, reconnecting_timeout or join_timeout. Explicit native failed/ended/auth/join-request failure records fail promptly with their numeric evidence. session_failed and run.json.failure retain those fields. The original deadline never resets on repeated states or admission transitions; an admission timeout means the host action did not complete within the configured budget, not that Zoom reported a network failure.

Failed/cancelled join cancels its handshake task and reader, closes its bridge, and tears down only its owned child/container before returning. macOS attempts SIGTERM (10 seconds), then kills its owned child if necessary (5-second wait); zoom_receiver_forced_stop records that fallback. Repeated session cleanup is safe. The native standalone probe is outside this Python voice-session watchdog. Output mute and semantic interruption are unchanged.
## Meeting workspace（MVP 骨架）

`src/sparkie/workspace.py` 提供 SQLite store，平台会议标识（`external_kind` + `external_id`，如 `zoom_uuid`）只用于 resolve，内部一律以 `ws_` 前缀的 `workspace_id` 为主键；Teams / Meet 之后用同样方式映射，agent 逻辑不感知平台。表结构：`meetings`（workspace_id、external_kind、external_id、title、status、created_at）、`transcript_events`（含 speaker、text、timestamp_ms、is_final、source）、`tasks`（instruction、status、created_from_transcript_id）、`artifacts`（type、title、summary、content_json/content_url、status）、`meeting_state`（active_artifact_id、current_topic）。`snapshot()` 是 GET 响应的完整形态。

`event_bus.py` 是内存 pub/sub：`publish` 给每条事件附加 `workspace_id` 和递增 `seq`；订阅者有界队列（默认 256），写满的客户端被移除而不是静默丢事件。同一 workspace 的 Zoom 面板与网页 workspace 订阅同一事件流。

`agent_runtime.py` 每条 ingest 的最终 human 转录产出动作列表：IGNORE / RESPOND / CREATE_TASK / PRESENT_ARTIFACT（Update/idea/decision 等记忆类动作后续以同词汇扩展）。路由目前是启发式：`wake.addressed_request` 判唤醒，研究类关键词建任务，"show us / 展示" 类呈现最近 ready artifact，其余唤醒请求发 `agent.respond` 事件（实际语音应答仍由 voice adapter/既有 engine 消费，runtime 不合成语音）。CREATE_TASK 存 tasks 表并发 `task.started`，异步 worker 完成后写 artifacts 表、发 `task.completed` + `artifact.ready`；PRESENT_ARTIFACT 写 `meeting_state.active_artifact_id` 并发 `artifact.present`。worker 签名为 `async (instruction, transcript) -> {type,title,summary,content}`；`--worker codex` 复用 `CodexTaskWorker`（真实后台任务），`demo` 返回明确标注 simulated 的占位 artifact。

`workspace_server.py` 由 `sparkie workspace` 启动（默认 127.0.0.1:8790，SQLite 存 `output/workspace.db`）：`GET /api/meetings/resolve?kind=..&external_id=..`（resolve_or_create；`reset=1` 时清空该 workspace 的 transcript/tasks/artifacts/meeting_state 并向订阅者广播 `workspace.reset`——会议号复用时每次入会开一张新画布，meetings 行与 workspace_id 不变）、`GET /api/workspaces`（全部 workspace + 计数，落地列表）、`GET /api/workspaces/<id>`（snapshot）、`GET /api/artifacts/<id>`（单个 artifact 含 content）、`GET /healthz`、`WS /workspaces/<id>/events`（广播流）。客户端消息：`{"type":"utterance","text":..,"speaker":..,"source":"human|bot","is_final":..}` ingest；`{"type":"end_meeting"}` 置 ended 并排队报告任务；`{"type":"cancel_task","task_id":..}` 取消运行中任务并发 `task.cancelled`；`{"type":"task_update","task_id":..,"status":..,"request":..,"result":..,"error":..,"error_type":..,"progress":..}` 把 live session 的 TaskCenter 生命周期 upsert 进 tasks 表并广播 `task.updated`（task_id 由会话侧拥有，与 runtime 自建的 `t_` 前缀 id 不冲突）；completed 且带 result 时落成 artifacts 行（content={markdown: result}）并广播 `artifact.ready`，可被 "show us" / artifact.present 投放。utterance 消息可带 `"live": true`：live session 的镜像转写不产生动作；Realtime 通过显式 artifact.control 指令选择展示，避免与会话自己的 agent 双重触发；浏览器 cancel_task 对镜像任务同样生效——`task.cancelled` 广播回到会话侧 WS，由 session 回调 TaskCenter.cancel 真正杀 job。websockets 的 HTTP 层不读 body，所有写入都走事件 socket；CORS 全开、无 share token 与鉴权，仅限本机 MVP。RTMS webhook、Zoom App 面板、`/m/<token>` 私链均未实现；voice output 仍走既有 MeetingAdapter/AudioMeeting 路径，不在此层。

`workspace_client.py` 是会议侧容错镜像：`realtime_session`（browser/local/zoom 三种 transport）与旧 `zoom_session` 启动时以 `reset=1` resolve workspace（zoom 用 `ZOOM_MEETING_ID` 作 `zoom_uuid` external_id），最终 human 转写与 assistant_transcript（bot source）镜像为 `live: true` 的 utterance，TaskCenter 的 `background_task` 事件镜像为 `task_update`（queued/running/completed/failed/cancelled 全程可见）；client 订阅广播流，`task.cancelled` 广播回调到 `center.cancel`，页面上的取消按钮可终止 live job；连不上服务器或任何发送失败都静默降级为 no-op，不影响会议。会话结束时发 `end_meeting`：runtime 置 `status=ended` 广播 `meeting.ended`，有转写且有 worker 时经正常任务管线产出报告 artifact（指令为转写内 Markdown 纪要），`ended` 状态会议的新 artifact 自动 `artifact.present`——会后打开页面即见纪要。页面 `/workspace.html` 展示转写、任务（含取消）、artifacts 与 stage；artifact.content 按 markdown/image/pdf/url shape 渲染，data URI 转 blob URL 供 PDF iframe。



### Workspace session generation and reset isolation

The meetings table now has a persistent integer generation (existing databases migrate to 0). Reset atomically clears the session tables and increments generation, cancels only that workspace's runtime jobs, and publishes workspace.reset with the new generation. Jobs capture generation before scheduling and check it before reading context, publishing errors, or storing results; even a worker that returns after cancellation cannot repopulate the new session. Cancellation does not undo external work already performed.

Resolve responses and snapshots expose workspace.generation. Clients connect to /workspaces/<id>/events?generation=<n>; a stale resolve-to-connect attempt closes with 4409. Writes carry generation and are ignored when stale; legacy sockets without this field stay bound to their connection generation. A live WorkspaceClient keeps its original generation and disables mirroring after a reset, including old end_meeting messages. Browsers adopt the new snapshot generation for subsequent cancel/utterance requests. Snapshots include the bus seq at read time; during reset refresh the browser buffers events and only replays events newer than that snapshot. Reset also invalidates old artifact fetches, hydration cache and active selection. This is session isolation, not authentication.

### Zoom microphone mute versus playback failure

Only ZoomMicrophoneMuted (the explicit N signal or a pre-send readiness check) is retried. Playback timeouts, malformed PCM and transport failures propagate as failures. PCM stays in the bounded buffer until a complete SDK packet acknowledgement; mute retains that packet, waits for microphone readiness, then retries after the existing native cancellation acknowledgement. Since partial packet progress is unknown, a mid-packet mute may repeat up to 100ms on recovery, but does not silently skip audio or report a dropped packet as played. A confirmed human interrupt or manual stop still cancels retained audio. Startup continues discarding input while _joining; post-join queued audio is drained without a startup flush.

### Optional semantic Zoom wake router

RealtimeAgent accepts an optional wake_router with async start(), classify(text)
and close(), plus model for diagnostics. classify returns accept or reject; only
the agent/output policy can authorize speech. SPARKIE_WAKE_ROUTER=devin selects
the dedicated tool-free Devin adapter with SPARKIE_WAKE_MODEL (default
gemini-3-5-flash-minimal). Unset/rules preserves the existing local policy. This
setting affects Zoom Realtime only and is independent of DEVIN_MODEL for tasks.

Final human text still enters meeting context once. Semantic classification runs
outside turn_lock and consumes the full final utterance. A monotonically
increasing local version fences acceptance against new speech, a newer final,
manual controls, input failure and shutdown. Old provider-output cancellation
does not invalidate a newer human decision. Explicit dismissal/manual-next controls
stay local; raw speech candidates and the 350ms recovery do not wait on the model.
Routing errors/2.5s deadlines fail silent for that utterance. Eligible task
notifications are deferred only while a decision is pending, then use existing
quiet/authorization rules. No task-worker conversation or lock is reused.

Diagnostics: zoom_wake_router_config, zoom_wake_router_ready/unavailable,
zoom_wake_routing, zoom_wake_router_failed (error_type, action, latency_ms when
available), zoom_wake_decision (semantic_router/local_control), and
zoom_wake_decision_discarded for late returns. Provider response bodies and
thoughts are not logged. See fast-wake-router-research.md for live-call evidence
and the remaining user-run Zoom validation.

### Semantic completion before Zoom wake routing

Zoom per-participant sessions default to SPARKIE_TURN_DETECTION=semantic_vad
(legacy deepgram is explicitly selectable). SemanticTurnEars pairs Deepgram
finalized word timestamps with a separate Realtime semantic_vad/medium detector for
each non-self participant. Both receive the same padded audio timeline. Only an
aligned complete turn becomes TranscriptEvent; Deepgram speech_final fragments
no longer call human_transcript individually in this mode. Fast text-confirmed
SpeechActivity.started still interrupts immediately, independently of completion.

SpeechActivity.stream_id may contain an adapter-local turn suffix. ParticipantEars
prefixes it with the participant and provider-stream serial instead of replacing
it, and tracks each active suffix separately. This prevents a late old stopped
event from clearing a new turn by the same speaker. Unsuffixed adapters keep their
existing IDs. Semantic mode supplies paced silence when callbacks stop and closes
idle provider streams after 15s; legacy mode keeps its previous 1.5s policy.

Alignment uses finalized result coverage or the audio frontier acknowledged by a
Deepgram Finalize response. A pending boundary times out after 5s. Detector or
alignment failure uses participant_input_failed and a semantic_turn_unavailable
coverage gap, without falling back to fragmented wake requests. Actual API
configuration, usage implications and validation are in semantic-turn-detection.md.

### Browser voice artifact board

The non-Zoom voice page at / embeds the existing workspace renderer in artifact-only mode. SessionController retains workspace_linked.workspace_id as workspaceId in /api/status independently of the bounded event history; it remains available after normal session end and is cleared on a new session. The page binds the iframe once per workspace, restores it on refresh, and clears the previous board while the next session connects. Voice controls and background-task cancellation/reporting remain in the parent page.

/workspace.html?workspace=<id>&server=/workspace-api&embedded=1 opens an existing workspace directly, without resolving a Zoom meeting or resetting it. Completed artifacts populate the catalog without changing presentation. Embedded mode restores only the explicitly selected artifact from the snapshot. Standalone navigation retains the full workspace view. The Vite /workspace-api HTTP/WebSocket proxy targets SPARKIE_WORKSPACE_SERVER (default 127.0.0.1:8790), so LAN clients use the same origin instead of connecting to their own localhost. Snapshot refresh after WebSocket subscription catches artifacts produced during initial connection. Workspace outages do not stop voice sessions; results remain in the original task list, and the board reports its connection state.


### Realtime artifact presentation controls and generation status

Devin/background workers produce content; Realtime owns presentation for live sessions. Realtime has list_artifacts, present_artifact(artifact_id), and hide_artifact tools through the injected WorkspaceClient. The catalog returns up to 50 recent metadata records (including task_id, title and status), not whole documents. Show/switch targets an actual ready artifact in the same workspace. Hide clears the shared active_artifact_id without deleting artifacts or cancelling jobs. Existing interrupted-response guards also fence these tool calls.

The workspace socket accepts artifact.control with action=list|present|clear, request_id, generation, and optional artifact_id. It returns artifact.control.result to the requester. Present persists selection and broadcasts artifact.present; clear broadcasts artifact.cleared. Invalid, unavailable, cross-workspace and stale-generation requests return explicit errors. Client requests use the existing two-second deadline; timeout means unknown outcome, never success. An acknowledgement proves server selection, not that every browser rendered it. Manual board selection uses this same server path. Live transcript mirroring no longer applies keyword-based presentation; legacy standalone/demo routing retains its existing behavior. Live-session end reports still generate but do not automatically replace the selected document after Realtime disconnects.

The board shows separate generation cards for queued/running tasks, with document shimmer animation while running and static waiting state while queued. Completion, failure, cancellation and reset remove the associated card; other in-progress tasks and the selected document remain visible. The animation indicates task activity, not incremental document contents or a measured completion percentage. Reduced-motion preferences disable motion.

Validation: 301 Python tests, 34 frontend tests, frontend build and both offline demos passed. An isolated browser fixture traversed actual Workspace HTTP/WebSocket, Realtime tool handling and presentation events: generation/stop, reduced motion, no automatic selection on completion, explicit present/hide, refresh and session clearing. No new real-model, microphone or Zoom acceptance was performed. Realtime tool result handling follows https://developers.openai.com/api/docs/guides/realtime-conversations .
