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

任务层使用独立异步 worker。Realtime 会把完成或失败通知入队，在当前用户轮次和音频播放结束后唤醒前台，由前台决定播报或 remain_silent。demo.py 尚未实现 worker。

## 会议报告

至少包含 meeting_id、标题、时间、参与者、overview、key_discussion_points、decisions、action_items、open_questions、tasks、transcript。action item 格式：`{text, owner: null|string, deadline: null|string, evidence_event_ids: string[]}`。owner 和 deadline 仅在 transcript 明确提及时填写。决策及行动项应可追溯到原始事件。

离线 harness 只产出最小回放包，完整报告元数据、摘要与页面由当轮编码负责人实现。模拟产物必须保留 `mode: mock`。真实报告禁止沿用固定内容冒充模型结果。

## Zoom 独立接收探针

`scripts/zoom-sanity.py` 通过 `--platform linux|macos` 或 `ZOOM_PLATFORM` 选择运行时，默认保留 Linux Docker。两平台共用 `sparkie.zoom_config` 生成凭证；macOS 原生接收器在 `native/zoom-macos/main.m`。探针模式（无 `voice` 配置）只输出音频诊断指标；macOS 接收器另有 voice 模式实现下方音频桥协议并接入 `AudioMeeting`，其实际会议语音验收尚未完成，不能用入会成功宣称完整语音闭环。

## Zoom 音频桥

`ZoomAudioMeeting` 实现相同 `AudioMeeting` 协议，使用 Linux SDK 7.0.5；`ZoomMacAudioMeeting` 复用同一协议，由原生 macOS 应用承载 SDK（7.1.5 基线）。Docker 内的 C++ 桥通过只发布到 127.0.0.1 的随机 TCP 端口与宿主 Python 通信；macOS 应用直接绑定 127.0.0.1 的每轮随机端口，令牌经权限 600 的 config.json 传入。先发送 64 字节随机会话令牌，再交换 `type:1 byte + length:4 bytes big-endian + payload`；每条音频为单声道 PCM16 32 kHz。

SDK → Python：`H` 握手，`M`/`N` 虚拟麦克风可发送/停止，`A` 音频，`S`/`D` 首帧提交/本次音频全部提交（4 字节播放 ID），`E` 固定诊断文本。Python → SDK：`P`（4 字节播放 ID + 最多 30 秒 PCM），`C` 取消播放。单连接、单次播放；两端都有有界队列，溢出或协议错误关闭本轮。C++ 在独立线程中按 20 ms 节奏发送 PCM，音频回调只复制数据，不执行网络 I/O。

`zoom_playback_submitted` 只报告 SDK 首帧接受，不能作为另一参会者的 DAC 时间或可听确认。`zoom-audio` 不设置 `audio_origin` / `last_playback_started_at`，不输出本地设备时延估算。Linux 混音输入在播放及之后 350 ms 替换为静音；这会失去同时发言，也不能在该窗口内靠语音取消。macOS 分用户路径见下文。

### macOS 分用户音频（SDK 7.1.5）

macOS 语音接收器改用 `onOneWayAudioRawDataReceived:userID:`；旧 nodeID 回调保留空实现以免重复处理。混音回调只发健康心跳，不转发混合 PCM。协议扩展：

- `U`：userID（4 字节 BE）+ 帧起始 timestamp_ms（8 字节 BE）+ PCM16 mono 32 kHz，总 payload 不超过 64000 字节。
- `J`：JSON 参会端列表，含 user_id、name、is_self；主线程每秒检查变化，音频回调不查询参会端信息、不执行网络 I/O。
- `R`：空 payload，混音接收健康心跳；静默会议也能就绪。

`AudioFrame` 新增可选 speaker_id、timestamp_ms，默认 None，保留既有调用兼容。时间原点为本轮 SDK 音频订阅附近；优先归一化 SDK getTimeStamp，返回零时用单调回调时间减帧长估计，不是精确声学时间。旧 macOS 二进制发出的 A 混音帧会明确报错要求重建；Linux A 协议保留。

`ParticipantEars` 按用户分流到独立 DeepgramEars，每条连接有独立断句器。无非零 PCM 的参会者不建连接；每人 1.5 秒无非零帧后补 500 ms 静音并关闭连接，之后发言建立新段，事件 ID 带用户和段编号。背景噪声可能使连接保持活跃，这不是语义 VAD。段内音频空隙补静音，长停顿以新的会议时间偏移处理。默认最多 32 条并行连接（含正在结束的连接），SPARKIE_ZOOM_MAX_STT_STREAMS 可调整为 1–64；每条输入最多 500 帧，超限或任一转写错误明确结束本轮，不静默串音或漏掉用户。

`TranscriptEvent` 新增可选 speaker_id（默认 None）；macOS 为 zoom:<userID>，speaker 为显示名，名字不可得时回退为 ID。重名用户不会合并，退会前取得的名字仍可用于最终转写。实时事件按提供者完成顺序到达；run.json 的 transcript 按 timestamp_ms 排序，问答上下文保留身份和时间。一个 Zoom 端内多人共用麦克风仍不能分开。

macOS 分用户模式只过滤 SDK 自身音轨，不采用上述 Linux 的全局播放静音门控；其他人的发言在播放期间仍可转写，远端扬声器回声仍可能被识别。分流测试和真实 Deepgram 合成音频测试不等于真实 Zoom 多人验收。

## Realtime 前台与后台分析（本地验收）

新的唯一网页入口 `/` 使用浏览器 AudioWorklet + `sparkie.realtime_session --transport browser`；`qa` / `wake` 仍可从旧 CLI 启动。
输入 PCM 分成两个独立有界队列：OpenAI Realtime 直接接收音频，Deepgram 只负责最终转写。
Realtime 不等待 Deepgram 的断句，也不等待 Codex 结果。Deepgram 网络失败会记录覆盖缺口，实时对话继续。

本地语音默认浏览器 autoGainControl=false、echoCancellation=true、noiseSuppression=true；Realtime input.noise_reduction=far_field，server_vad threshold=0.5、prefix_padding_ms=600、silence_duration_ms=600，保留 create_response / interrupt_response。realtime_ready 记录服务端返回的实际 noise_reduction 和 turn_detection。无清晰语音时可调用 remain_silent，不据此伪造用户说过的话；该工具统一记录 realtime_silent，替代原本仅表示后台通知延后汇报的 background_notification_deferred。

`RealtimeAudioTransport`（`audio.py`）使用 PCM16LE、mono、24 kHz：`join` / `audio` / `append_output(item_id, pcm)` / `finish_output(item_id)` / `stop_speaking` / `leave`。
`append_output` 必须立即入有界播放队列；`finish_output` 只标记生成完成，不表示音频已播放。
`outputs` 保存每个 item 的字节数、取消标志和 `played_ms()`；打断会清空待播内容并向 Realtime 发送截断时间，防止未听到的内容留在模型上下文。
本地实现使用 PortAudio DAC 时间估算实际播放进度。Zoom 当前 32 kHz 整段播放协议不满足该接口，需另行实现流式播放、24↔32 kHz 重采样及可靠的播放进度；不能直接声称兼容。

`delegate_task(request)` 立即返回 task_id、queued、awaiting_background 和上下文记录数；`task_status(task_id)` 返回状态和已完成结果；`cancel_task(task_id)` 取消任务。
`update_task(task_id, request)` 接收完整修订请求并刷新快照，保持任务 ID。queued 任务保留队列位置；running 的 Devin 任务通过队列传递修订，ACP 中断当前轮后在同一会话继续。返回 update_delivery=pending 不能宣称已执行；applied_revision 和 delivered 表示已送入后台连接。request_history 保存历史请求，连续修订以最新完整请求为准。其他 running 后端及 completed 任务拒绝更新，已发生的操作不会回滚。
`create_desktop_file(filename, content)` 和 `open_website(url)` 使用同一任务状态/通知协议，但直接执行本机操作，不占 Codex 串行队列。文件使用独占创建并读回核验；网址仅允许 HTTP(S)，结果只确认浏览器启动请求，不保证页面加载完成。
worker 异步排队执行，提交立即返回；无每会话任务数量上限，也无单任务超时。取消 Codex 任务会终止对应进程；取消 Devin 当前轮保留常驻会话，结束语音会话会终止进程组。
`task_workers.py` 选择独立 Codex / Devin 适配器，Devin 协议实现位于 `devin_acp.py`。共用 `run(request, transcript)` / `run_with_progress(request, transcript, progress)`；持久 worker 另提供 start / close，支持运行中修订时通过 updates 队列接收 `(request, snapshot, revision)`，initial_revision 表示开始运行时的修订号。`SPARKIE_TASK_BACKEND=codex|devin` 仅选择 Realtime 后台，默认 codex；DEVIN_MODEL 默认 swe-1-6-fast。前台语音及旧 Q&A SPARKIE_BACKEND 不变。

Devin 每次语音会话启动一个 `devin acp --model ...` 进程，经 initialize / session/new / session/set_mode 建立无审批会话；后续串行发送 session/prompt，共享历史。session/update 仅提取公开回答和工具类型/状态，忽略思考内容及原始工具输出；session/request_permission 复用已有用户授权，仅选择当前会话的 allow_once 选项。取消用 session/cancel，5 秒无应答则杀进程组；连接断开、RPC 错误、非 end_turn、空结果均不能作成功。进程断开不自动重启或重放任务，避免重复外部操作及丢失上下文。取消确认期限和 60 秒启动期限不是任务超时。

会话发出 task_backend_config、task_backend_starting / task_backend_ready / task_backend_failed。运行任务包含 backend/model、agent_session_id、agent_pid、revision/applied_revision 和 update_delivery。常驻进程在项目目录继承 CLI 登录与工具配置，移除语音 OPENAI_API_KEY。完整快照的临时文件存续到语音会话结束；TaskCenter.close 终止进程并清理临时目录，新语音会话不继承旧 ACP 上下文。
委派时完整最终转写、生成的助手文本、播放截断标记、覆盖缺口一并快照，不再受旧问答的 50 条限制。
尚未到达的 Deepgram 转写不会伪装成已收集：工具描述要求前台补充当前请求与最近口述；任务记录明确快照截止语义。
完整上下文落盘，路径交给 Codex 读取，不截断到固定提示词长度。按用户授权，Codex CLI 加载用户配置和现有集成，工作目录为实际项目目录，使用 `--dangerously-bypass-approvals-and-sandbox`、`web_search="live"`；可读写文件、执行 shell、研究网页和调用配置的工具。不再传入 ignore-user-config / shell_tool=false / read-only。仅从子进程环境移除语音 OPENAI_API_KEY，以继续复用 CLI 登录；其余工具环境继承。外部服务是否可用仍取决于实际安装与登录状态。

`output/realtime/<session>/transcript.jsonl` 保存全部记录，`tasks.json` 保存任务、执行时的输入快照和结果，`events.jsonl` 保存诊断事件，`run.json` 保存会话报告；不保存原始音频。Codex JSON 事件只提取执行步骤与用量元数据作为 progress，不把原始命令输出或 stderr 转发到前端。
转写持久化成功后才发送 UI 事件。助手的完整生成文本不代表全部已播放，以 `realtime_interrupted` 为准。
网页默认使用浏览器 `getUserMedia(echoCancellation: {exact: true})`，检查实际 track settings 并将处理后的 PCM 并行发送给两个 provider；不会在 AI 播放时门控人声。浏览器不支持时明确启动失败，不静默退化成无保护双工。旧 local CLI 的扬声器门控仍写入 coverage_gap / coverage_resumed。
结果完成或失败后更新界面，同时向 Realtime 投递包含任务结果的系统通知并触发 response.create。每个任务只通知一次，忙碌期间排队，多个完成结果合并唤醒；等待用户轮次与全部本地音频播放结束。前台自行决定直接汇报或调用 remain_silent（不生成后续语音），结果保留在对话上下文。用户问进展仍可用 task_status；手动 report_task 仍只在空闲时执行。通知循环随会话关闭取消；断开后不跨会话自动重投。
页面只显示对话与任务，诊断事件仍可在日志中查看；`realtime_audio_started.latency_ms` 是最近口述结束到设备首音频的估算，不是后台任务最终答案延迟，也不是独立声学测量。

### Browser audio transport

WebSocket `/audio?session=<id>` 仅接受通过本机网络接口地址的同源 Origin、当前会话和一个连接，PCM 不进入状态轮询或磁盘日志。browser→Python：audio_settings、连续 sequence 的 audio_input、带 generation 的 audio_progress。Python→browser：audio_ready、audio_output、audio_clear。只有 provider ready 后才发输入；24 kHz PCM16 mono、20 ms 包；队列/管道溢出明确失败。清空播放递增 generation，旧音频/播放进度不能复活。AudioWorklet 每 20 ms 报告渲染进度供截断使用，不宣称是准确 DAC 时间。密钥仍仅保存在 Python。浏览器断开关闭会话并释放麦克风。

Realtime 工具回调立即回传 queued，后台不阻塞音频事件循环；工具续答使用 response_pending 避免重复 response.create，用户发言期间不抢建回复。前台对外部信息、网页检索、复杂文件/代码和外部工具请求应直接委派；简单桌面文件创建与打开指定网址优先使用上述本机工具。

浏览器 `seconds=0` 表示手动结束；本地 PortAudio 模式仍要求 10–300 秒。浏览器输入包续期页面及音频心跳，输入停顿只提示恢复麦克风，不取消后台任务；关闭页面、断开音频 WebSocket 或显式结束仍终止会话。`browser_audio_settings` 包含 AudioContext 和 track 状态，供排查暂停/设备中断。

Realtime 的 Deepgram 适配器可通过 on_partial 回调发出 `transcript_partial`。网页服务将其合并为 `partialTranscript` 状态，显示“正在转写”，不加入最终事件历史、持久转写或任务上下文。最终 transcript 或连接结束清空预览。识别修订可替换预览，只有最终 transcript 可作为任务依据。

`audio_input_diagnostics` 每累计两秒输入记录一次 RMS dBFS、峰值、削波比例、全零采样比例和最大包间隔；只保存统计，不保存音频。browser_audio_settings 另含实际设备标签、autoGainControl 和 trackEnabled。页面显示是否正在接收声音，并在 15 秒内两次回复被取消时给出暂时提示；该提示不能证明是回声或噪声，也不改变自动打断行为。
