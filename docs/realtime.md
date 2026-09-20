# Realtime 本地验收

网页唯一入口 `/`：浏览器收音/播放 → Realtime 实时对话，同时 → Deepgram 人类转写；Codex 或 Devin CLI 异步执行工具任务。Zoom 已通过同一会话入口接入，见下文；真人 Zoom 验收仍待完成。

macOS Zoom Realtime 同时接收连续混音供前台语音、分用户音轨供 Deepgram 转写，保留用户 ID 与显示名。wake/qa 为 legacy，不是本轮验收入口。新双路协议必须重新构建 macOS receiver；浏览器语音不依赖此接收器。

## 运行

配置 `.env` 中 OPENAI_API_KEY、DEEPGRAM_API_KEY；后台复用所选 CLI 的登录和已有工具配置。

### 选择 Devin 低延迟配置

后台提供者由独立的 `SPARKIE_TASK_BACKEND` 选择，默认 `codex`；旧问答入口的 `SPARKIE_BACKEND` 不受影响。Devin 使用本机 CLI，不创建 Devin Cloud 会话。先安装并登录 Devin，再在 `.env` 设置：

```dotenv
SPARKIE_TASK_BACKEND=devin
DEVIN_MODEL=swe-1-6-fast
```

用 `devin auth status` 核对登录，`devin models list` 核对当前账号的模型 UID。`swe-1-6-fast` 是本机 CLI 3000.10.31 已列出并实测的型号；其他账号的可用性需自行核对。配置只影响新会话，结束当前对话后重新开始。workspace 服务未显式指定 --worker 时也沿用 SPARKIE_TASK_BACKEND，修改后需重启服务。切回 Codex 使用 `SPARKIE_TASK_BACKEND=codex`。

2026-09-19 workspace 集成修复：269 项 Python 测试、30 项前端测试、生产构建和 primitive/demo 离线检查通过。覆盖重置后的旧任务/旧连接隔离、浏览器迟到请求、播放超时不能冒充静音成功，以及静音恢复重试未确认音频包。真实 DevinTaskWorker 使用 swe-1-6-fast 的无工具回复检查通过（冷启动加回复共 1422ms）；该数字不是唤醒分类或会议语音延迟。本轮没有重新进行真实 Zoom 静音/恢复验收；若 SDK 在包内中断，恢复可能重复最多 100ms，无法据此声称无缝续播。workspace 服务结束时会关闭常驻 Devin worker。

Devin 使用常驻的 ACP 标准输入/输出连接。每次语音会话启动时并行初始化一个 CLI 进程和一个 agent 会话，不阻塞前台语音连接；之后的后台任务、追问和修改都复用该进程与上下文。使用现有登录、工具配置和项目目录，保持无审批权限，不设置单任务超时。启动握手有 60 秒上限，失败只影响后台；不会静默切换成另一个无上下文的 agent 或自动重放任务。

前台可持续调用 delegate_task、task_status、update_task、cancel_task。update_task 接收**完整修订后的请求**：排队任务直接更新，运行中的 Devin 任务先通过 ACP 取消当前轮，再在同一会话送入修改。返回 pending 只表示接收排队；applied_revision 和 update_delivery=delivered 表示已写入后台连接，不表示任务完成。已经发生的文件或外部操作不会撤销。普通取消保留 agent 会话供下一轮使用；5 秒未确认取消则终止进程组，并拒绝在失去上下文后静默继续。

「结束对话」、关闭页面或音频连接断开会关闭该 agent 进程组；下次「开始对话」建立新会话。目前不跨语音会话恢复。转写快照放在会话专用临时目录，保留到会话结束，便于后续轮次引用。CLI 自己仍可能保存会话历史。语音 OPENAI_API_KEY 不转发给 CLI。

会话记录 task_backend_starting / task_backend_ready / task_backend_failed，任务记录 agent_session_id 和 agent_pid 便于核对是否复用。任务卡片显示模型与工具阶段；只提取 ACP 工具类型、状态和公开回答，不展示思考内容、原始命令输出或凭据。

2026-09-19 真实验证：同一进程与同一 ACP 会话连续四轮，启动 4.55 秒；记住随机测试内容 2.92 秒；依据上一轮记忆创建并核验文件 3.83 秒；运行中修改等待任务后 1.49 秒返回新结果；最后追问原内容 0.84 秒。独立读回文件核对内容，结束后进程已退出。这是后台任务实测，不是语音端到端延迟或受控性能对比；旧 print 模式的一轮完整任务曾耗时 39.2 秒。当前桌面文件创建和打开网址也统一委派给后台。模型依据：[Devin 模型说明](https://docs.devin.ai/cli/models)和当前账号 CLI 列表。

```bash
bash scripts/web.sh
# http://127.0.0.1:5178/
# 并行开发端口：
SPARKIE_WEB_PORT=5179 bash scripts/web.sh
```

开发服务器监听 `0.0.0.0`，可通过本机局域网 IP 和端口访问。API 与音频 WebSocket 接受本机网络接口地址的同源请求，拒绝其他来源。跨设备访问 HTTP 页面可查看界面，但浏览器麦克风需要可信 HTTPS；localhost 的安全上下文例外只适用于访问者自己的设备。HTTPS 页面使用 wss 音频连接。

点击「开始对话」后浏览器申请麦克风权限。默认手动结束；也可在设置中选择限时测试。默认英语转写；中文在设置中选择。网页要求浏览器回声消除并校验 track settings，不再要求扬声器播放期间按按钮才能打断。麦克风经同一个 AudioWorklet 连续送给两个 provider，AI 回复使用其自身输出文本。原 PortAudio CLI 仍可用，其扬声器模式是旧的半双工保护。

浏览器音频短暂停顿会显示「恢复麦克风」，保留会话和后台任务；点击后重新连接输入设备并恢复 AudioContext。浏览器输入包直接刷新音频心跳，不依赖 Python 返回电平事件。页面关闭、音频 WebSocket 断开、提供者错误或用户结束仍可能终止会话。麦克风中断的设备/系统原因需结合 `browser_audio_settings` 中的 contextState、trackState、trackMuted 排查。

说话时会显示「你 · 正在转写」的临时预览，断句后才成为正式记录；临时文字可能修订，不进入后台任务上下文。连续被声音打断的回复会显示提示，持续说话时显示等待说完。诊断日志包含输入电平、削波和包间隔统计以及实际设备状态，帮助区分“没有音频”与“有音频但还没断句”，不录制原始声音。此提示不代表已经确认回声、环境噪声或具体设备故障。

内置麦克风/扬声器自测复现过测试语音结束后 Realtime 长时间保持 speech_started、回复被取消的问题，期间仍持续收到音频。当前浏览器关闭自动增益，保留回声消除和噪声抑制；Realtime 使用 far_field 降噪、0.5 的 server_vad 阈值、600 ms 起点前缓冲与 600 ms 断句等待，仍允许用户打断。尝试过 0.8 阈值，但中文短句出现语音检测启动过晚，因此未保留。无清晰人声时要求前台保持安静，不重复问候。耳机、轻声真人及自然打断场景仍需验收。依据：[OpenAI 音频会话配置](https://developers.openai.com/api/reference/resources/realtime/subresources/sessions/methods/create)和 [VAD 指南](https://developers.openai.com/api/docs/guides/realtime-vad)。

结束会话的前端强制退出宽限为 10 秒，留给转写刷新和各提供者连接清理；超过期限仍记为失败。此期限不影响运行中后台任务的执行时长。

## 委派和工具权限

前台提示词要求普通回答为一到两句短句，委派确认一句，任务完成时先说主要结论、最多三句短句，细节留在任务面板，用户要求时再展开。目标明确但部分词未听清时，只委派听清的目标和细节，让后台核对相关的人声转写；不猜姓名、地点、日期或数字，不添加候选解释或臆测的歧义。转写可能延迟、错误或缺失，后台无法确认必要信息时再简短追问。提示词变更在新语音会话生效；这不是转写完整性或识别准确性的保证。

所有文件操作（包括桌面文件创建）、打开网页或本地 HTML 报告、网页检索和代码执行，都通过 delegate_task 交给所选 Devin / Codex 后台。Realtime 仅保留 delegate_task、task_status、update_task、cancel_task、remain_silent 五个工具；已移除创建桌面文件和打开页面的本机快捷工具及执行分支。

后台完成或失败后会主动唤醒前台，由前台决定汇报或保持安静；结果也显示在页面，可口述询问或点播报。后台一次处理一个任务，其他委派任务排队，前台语音不受该队列阻塞；简单文件与打开页面请求也会排队。Codex JSON 与 Devin ACP 事件提供当前工具阶段。用户补充任务信息时，通过 `update_task` 更新原任务；Devin 支持运行中修订，其他后端仍只支持排队中更新。

按用户明确授权，后台加载既有 Codex 配置、技能与工具，使用实际项目工作目录，开放 shell、网络和文件读写，关闭沙箱和审批；移除原来的每任务 90 秒超时与每会话八项任务上限。服务集成仍需要自身已安装和登录。语音 OPENAI_API_KEY 不传入 Codex，以保持 CLI 登录计费。原固定回复/旧 Q&A 模式的隔离规则不受影响。

后台读取委派时的完整转写文件，包括覆盖缺口与生成的助手文本；当前口述可能比 Deepgram 更快，由前台把完整请求一起传入。会话结束或主动取消会终止运行中的任务。原始音频不会保存；转写、任务和结果在 output/realtime/ 下。

## 验收

1. 正常问答；AI 说话时直接开口，检查停止播放并听取新请求，且不被自身声音误触发。
2. 说“查一下最新的 Zoom SDK release notes”，应出现后台任务，而非回答无法联网。
3. 任务运行中继续说“先讲个笑话”，前台应即时回复；之后保持安静，验证任务完成会唤醒前台并汇报结果。要求“完成后先别说”时应保持安静。
4. 请求创建一个测试文件，核对实际文件和后台结果；取消 Devin 任务应停止当前轮，并保留同一进程以处理下一任务；结束会话才退出进程。
5. 点「静音」停止麦克风输入，AI 仍可播放；取消静音恢复收音。结束或关闭页面后麦克风停止。按转写语言选择中文/英文；固定中文识别英语会明显退化。

## 已验证与待验证

- 2026-09-19 物理音频自测：macOS 合成测试语句，经 afplay 从 MacBook 扬声器实际播放，由内置麦克风和浏览器原生 getUserMedia 收音，连接真实 Deepgram 与 Realtime；未将测试音频直接注入 WebSocket 或替换麦克风。初始配置出现英文问候转写正确、回复连续取消、20 秒无输出音频，证据在 output/acoustic-voice/20260919T190636/results.json。最终配置的 output/acoustic-voice/20260919T191638/results.json 中，连续英文问候和“二加三”均正确回复，测试语句播放结束至回复文本分别为 1.403 秒和 1.298 秒；中文“二加三”转写识别出数字，但 Realtime 在 1.873 秒后错误回答“4”，中文正确性仍未通过。最后一组各回复后的约八秒观察窗内无额外回复或取消，全部生成音频均由浏览器 AudioWorklet 渲染完毕，两次会话显式停止均正常结束。上述时间不是扬声器首音延迟；渲染完成也不代表人工听音验收。这是合成语句经真实物理设备的测试，不是 Zoom 或真人会议验收，也未验证后台任务的语音委派。
- 2026-09-19：复现旧版后台串行排队与 `audio-stalled` 六秒强制停止。完整 Codex 小文件对照任务耗时约 41–90 秒；当时的本机文件工具（现已移除）独立执行并核验约 21 ms，真实 Realtime 文本指令选择该工具后完成文件创建，连接就绪至任务完成约 0.7 秒。测试文件已清理；此数据不等于真人语音端到端延迟。
- 浏览器合成静音输入经真实提供者连接：暂停 AudioContext 超过六秒后会话仍保留，点恢复后继续输入，显式结束正常退出。没有用合成流代替真人收音验收；底层输入停顿原因尚未确诊。

- 真实 Codex worker 已调用 shell 写入并读回测试文件，验证不止是提示词声称具有权限。
- 真实 Realtime 自动把“查最新 release notes”交给工具；控制为未完成的后台任务运行时，前台继续回答下一轮中文问候。此测试验证委派/并发，不冒充完成真实网页研究。
- 浏览器真实 AudioWorklet 合成输入测试：24 kHz、480 samples/包，并报告支持 echoCancellation；没有打开用户麦克风。实际 track 设置会在正式开始时校验，扬声器回声效果和自然语音打断需真人验收。
- 真实本地 WebSocket → Python → provider 连接以合成静音验证，非真人收音测试。
- 真实 Realtime 已通过固定后台测试结果验证自动汇报与 remain_silent 两种选择；这不代表真实 Codex 任务在该测试中执行。
- 单元测试覆盖输入持续采集、输出清空、旧 generation 丢弃、任务取消、转写持久化及回复续接。

参考：[浏览器回声消除](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackSettings/echoCancellation)、[Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations)。


## Zoom 中验收完整 agent

本机完成原生构建后，直接运行：

```bash
uv sync --frozen
ZOOM_PLATFORM=macos bash scripts/zoom.sh --language en-US --seconds 3600
```

需要 `OPENAI_API_KEY`（Realtime）、`DEEPGRAM_API_KEY`（并行转写）、既有 Codex CLI 登录和 Zoom 配置。默认 Realtime 模型沿用 `OPENAI_REALTIME_MODEL`，后台沿用 `CODEX_MODEL`。不会用固定 “I'm here.” 代替语音 agent，也不会调用 Deepgram TTS。`--response-mode wake` 仅用于诊断。

主持人接纳 Sparkie、允许录制权限，看到 `listening_ready` 后：

1. 从另一台参会设备说“Hey Sparkie”并提出问题，确认听到与问题相关的自然语音回答；未称呼时应持续监听但不播放。
2. 请它调研一个需要外部信息的问题，检查出现 `background_task`，状态由 queued/running 进入 completed 或 failed。
3. 后台进行中继续提出普通问题，确认前台可以响应；等后台完成后，检查结果通知及语音汇报。以来源/实际产物核对结果，不只看“完成”文本。
4. 两位参会者轮流和同时发言、同名/改名、停顿后继续，核对 transcript 的 speaker_id、speaker、timestamp_ms。检查后台任务快照仍保留这些字段。
5. Ctrl+C 结束，确认 Sparkie 离会、后台任务停止；检查 `output/zoom/<session>/` 中的 transcript.jsonl、tasks.json、events.jsonl 和 run.json。

真实 Zoom 多人验收待进行。macOS 分轨 VAD 已接通语音打断，前台改用分轨最终文本；Linux 混音路径仍受播放及后 350ms 门控限制。macOS 过滤机器人自身 ID，远端声学回声仍可能被识别。流式输出以 100ms 包提交（包内由 SDK 桥按 20ms 发送）；提交进度不等于另一端听到的时间，真实延迟、音质及并发体验仍需上述验收。浏览器入口保持现有 AEC 和语音打断行为。


### 分轨打断验收

输出策略边界修复：原始 Deepgram VAD 现在只暂缓播放 350ms，期间保留已生成音频；首个包含文字的 interim/final 才正式取消。350ms 内没有确认则继续剩余 PCM，重复噪声不延长该窗口；当前已提交的 100ms 包不能撤回，窗口后晚到的文字确认仍可打断。显式 mute/stop 不自动恢复。分轨仅排除 SDK 自身音轨，不能保证消除真人麦克风重新录入的扬声器回声；可识别成文字的回声仍可能触发正式打断，实机扬声器验收不可省略。

后台结果播报从一次性通知队列唤醒改成检查持久 pending 状态：普通人声只暂时让出发言，结束后安静 750ms 即可重新报告已授权任务的完成/失败结果；明确静音则等新的唤醒或手动报告。unmute 的下一轮权限不会被后台结果抢走，已 offered/confirmed 的结果不会自动重复。取消任务等指令不再被 stop/cancel 前缀误判成静音；关闭输出链后迟到的工具调用也不会执行。

扬声器验证建议：先说 “Hey Sparky, explain the proposal in detail”，播放时制造一次短噪声，观察 zoom_barge_in_pending → zoom_barge_in_false_alarm 后从剩余音频恢复；再说出清晰语句，确认正式停播。随后委派一个只读后台任务，期间继续讨论，确认任务结束后在安静时主动报告，无须再次唤醒。最后测试明确 “Hey Sparky, stop” 不会在 350ms 后恢复。

2026-09-19 本轮验证：246 项 Python 测试及 primitive/demo 离线检查通过；续播测试逐字节核对剩余 PCM，覆盖重复候选、迟到确认、明确静音、通知重试与手动打断后的显式报告。真实 en-US 会话 20260919T230707-517aad7e 在 15404ms 就绪；疑似打断 62642→62992ms、67822→68173ms 后恢复保留音频；后台任务在 119073ms 完成，119153ms 自动打开结果播报，120050ms 首次提交播报音频。用户对扬声器下的误打断续播、真人打断与后台自动汇报测试回复“Good”。这些时间是本地日志时钟；未测量远端停止延迟，也不构成通用声学回声消除的证明。本轮 Python 修复无需重建原生 receiver；最终补充的手动 interrupt/report 控制边界仅由离线测试覆盖。

启动回归修复（2026-09-19）：多音轨合并后的麦克风设置改成了非静音入会，实测出现 source 已初始化却没有 onMicStartSend；Python 等待发送就绪时，A 混音无人消费，约 10 秒堆满，U 分轨却能提前触发无法播放的回答。现恢复原先的静音入会 → 安装外部音源 → 取消静音顺序，移除自动反复取消静音，并在 join 完成前明确丢弃 A/U 音频，记录 zoom_startup_audio_discarded 和 startup_frames_discarded。请在 listening_ready 后开始唤醒测试。

232 项 Python 测试及 primitive/demo 离线检查通过；新增用例重现超过 1000 帧的启动积压，并验证麦克风缺失时正确超时、延迟就绪后两路输入恢复。原生接收器重建及签名检查通过。真实会话 20260919T223648-a87f017f 已出现 zoom_microphone_ready（75941 ms）、listening_ready（78164 ms）和首次 zoom_playback_submitted（91734 ms）；随后混音持续被消费，未再出现此次启动积压。本轮用户已明确确认在 Zoom 另一端能听到回复；会话在就绪后运行满 180 秒，以 duration_elapsed 正常结束，进程退出码为 0。此确认仅覆盖实际发声及本次启动回归，远端听到的打断停止延迟仍待验收；程序内 remote_audibility_verified 不自动改为 true。

本地实现与离线测试不代替真人会议验收。先重建接收器，运行：

~~~bash
uv run --frozen python scripts/zoom-sanity.py build --platform macos
ZOOM_PLATFORM=macos bash scripts/zoom.sh --language en-US --seconds 3600 --response-mode realtime
~~~

1. 用两个独立 Zoom 端参会，按实际使用场景用扬声器测试。说“Sparkie, explain this proposal in detail”，在回答过程中发出短噪声：预期暂停后在 350ms 窗口结束时继续剩余音频。再开口“Let’s discuss this first”：原始 VAD 先暂停，首个有效 interim/final 确认后取消，普通讨论不授权新回复。耳机仅作为区分声学回声的对照测试。
2. 再唤醒，播放时说“Sparkie, just give us the conclusion”。预期停掉旧音频，完整保留新的请求，听完之后生成新回答；没有旧句子续播或两段音频重叠。
3. 说“Sparkie, stop”或“cancel”，保持安静时不恢复。随后新的 Sparkie 唤醒可重新开口。
4. 两位参会者重叠发言，任何一位确认发言都能取消 Sparkie；有效请求的回答等待所有确认发言的音轨结束。只有噪声候选的音轨不能永久阻塞回复。没人说话时，Sparkie 不能仅因自身 SDK 音轨而停止。
5. 在终端输入一行 {"action":"mute"} 检查停止；再输入 {"action":"unmute"} 后说不带唤醒词的请求，只有下一轮获准回复。打断前后的后台任务 ID/状态应保持连续。
6. 核对 events.jsonl 的 zoom_human_speech_started → realtime_interrupted → transcript → zoom_human_speech_stopped → zoom_response_requested，以及 cancelled response 的迟到音频被丢弃。语音开始事件与模型事件可能因网络异步交错；只有远端听音/经同意的录音才能测量真实停止延迟。

分轨打断初次接通的验证记录（启动回归修复前，2026-09-19）：

- Python 230 项离线测试、primitive/demo 模拟通过；前端 26 项测试及三个页面生产构建通过。
- 仓库 participant-1.wav（32 kHz 单声道测试录音）经真实 Deepgram + ParticipantEars：测试开始后 296 ms 收到 started，2903 ms 收到最终转写和 stopped。只证明提供者会先发送语音开始事件；不是 Zoom 网络或远端停止延迟。脱敏结果保存在本地 .runtime/zoom-barge-in-deepgram.json。
- macOS receiver 重新编译、签名验证通过；独立 SDK check 停在 SDK_INIT_BEGIN 后超时，工具提示检查系统钥匙串授权。尚未证明该超时的具体原因，未据此声称真人 Zoom 打断成功。

当前限制：Deepgram 首次分轨连接和 VAD 网络延迟会影响停止速度；最终文本延迟决定重新回答的时机。过滤 SDK 自身 ID 不等于声学回声消除；共用同一 Zoom 端也不能分人。分轨服务失败会停播并记录 zoom_barge_in_unavailable，后台继续，自动语音需重启恢复。真人远端停止延迟仍待验收。

### 终端输出背压修复

本地会话 `20260919T171253-ac5d40a5` 在 107742ms 的 `BlockingIOError` 紧跟播放事件输出，随后 5100ms 播放等待超时。该时刻 SDK 日志已完成第 335 包发送，收音仍持续；Python 队列最大仅 3 帧。以写满的真实伪终端复现：同步 stdout 打印抛错，中断接收循环，已到达的播放完成确认未被处理；错误日志自身再次抛错还会跳过原来的清理。

现在 stdout 通过 `EventOutput` 有界异步队列输出，支持部分写入、EAGAIN 等待和断管处理。CLI 终端长期堵塞时只省略终端副本，完整事件仍先写 events.jsonl；run.json 的 event_output 记录省略数量和输出错误。网页 stdout 承载音频协议，不能省略，溢出会明确失败。音频接收异常会先唤醒播放等待者并停止采集，再输出诊断，避免第二次超时掩盖原始错误。

已做真实伪终端/管道的离线回归；仍需真人重跑原场景确认，不将离线复现等同于整场会议稳定性验收。本修复不改变模型、音频采样率或 Zoom SDK 配置，无需重建原生程序。

Zoom Realtime 的 --seconds 范围为 1–3600 秒，从 listening_ready 开始计时；建议会话使用 --seconds 3600。到期记录 session_duration_elapsed / exit_reason=duration_elapsed，正常退出（也会结束尚未播完的回复）；Ctrl+C 仍为 stopped。前台混音在播放及尾音 350ms 门控，不支持语音打断；macOS 分轨转写不受此门控影响；可用终端 interrupt 控制取消。

### Interrupting without losing task results

The terminal still accepts one JSON command per line: {"action":"interrupt"} stops all queued output and waits for the next user turn. In Zoom speaker mode, the mixed microphone remains echo-gated while Sparkie speaks; interruption during that window requires this control or a trusted separated-human producer.

A separated-human producer can send human_turn/start immediately and human_turn/commit with final text after the user finishes. This selects external-text input for the session; all later turns must use those controls. See [the control contract](interfaces.md#semantic-interruption-and-trusted-human-controls) for examples, delivery acknowledgements and integration boundaries. Speaker separation itself is not implemented here.

Task results whose announcements are cut off remain pending for fresh generation after the user's turn. Generated or SDK-submitted speech is never marked heard automatically. Fully submitted, uninterrupted announcements remain unconfirmed without repeatedly waking the agent; explicit human confirmation prevents later automatic reannouncement.

Focused offline validation: uv run --frozen python -m unittest discover -s tests -p test_semantic_interruption.py -v. These tests use a fake audio bridge and WebSocket and provide no live audibility evidence. Native cancellation protocol is unchanged; no SDK rebuild is required for this feature.

### Zoom 默认输出静音（当前 MVP）

2026-09-19 的 211322 会话已正常收音，但最终转写把称呼连写为 hellosparkie，并聚合在前一段讨论后的第二句，旧规则因此未创建回复。现在 Zoom 按明确句末标点检查后续句首，并只补全该精确 hello+名字连写的空格；不做模糊匹配。最小复测说“Hello Sparkie”，查看 zoom_wake_decision(decision=wake) → zoom_output_state(muted=false) → zoom_response_requested → realtime_response_started → zoom_playback_submitted；回答生成完成且队列排空后应出现 zoom_output_state(reason=chain_drained, muted=true)。SDK 提交仍不等于远端听到，必须由另一参会端确认。

以上 Zoom 普通问答步骤现在需要句首点名，例如 “Hey Sparkie, explain the architecture in detail”。只关闭 Sparkie 的 Zoom 输出；Realtime 会话/输入上下文、Deepgram 和 Codex 后台任务持续运行。未点名的普通会议发言进入现有 Realtime 上下文，但不会触发无必要的助手生成。浏览器/local 模式不变。

使用原有 Sparkie/Sparky（可带 Hi/Hey/Hello）最终转写唤醒；完整回答和所属工具续答结束、队列排空后自动静音。没有 12 秒或其他产品发言时长截断；保留有界音频积压保护及会话总时长。授权请求产生的后台任务，其结果通知可以单独唤醒输出；其他任务不能。

终端每行一个 JSON：{"action":"mute"} 停止并清空全部播放，不取消后台任务；{"action":"unmute"} 仅允许下一条最终人类转写触发一条回答链，不恢复旧音频。也可说 “Sparkie, stop” / “不用了”等既有取消词；播放期间 Zoom 混合输入仍受回声门控，需终端或可信分离人声控制实现该窗口内取消。普通混合 VAD 不再自行打断 Zoom 回答，最终文本负责 wake/cancel。

测试时分别核对：未点名讨论零输出；长回答完整；自动重新静音；后台任务归属；mute/unmute 不复活旧音频。使用同一会话观察输入/转写持续。SDK 提交不代表远端听到；需另行真人验证最终转写延迟、音质、停播残留和误唤醒。完整契约见 interfaces.md 的 Zoom output mute MVP。

## 语音测试页内的成果面板

无需 Zoom 或会议号。启动 Workspace 后端和语音前端：

    uv run --frozen sparkie workspace --host 0.0.0.0 --port 8790 --worker devin
    # 另一个终端
    cd frontend
    npm run dev

打开 http://localhost:5178/，开始对话并委派任务。Artifacts 区自动绑定本轮语音会话；任务生成期间显示动画，完成后由 Realtime 根据对话选择展示；支持 Markdown/表格、图片、PDF、链接及原有下载和展示操作。「独立打开」可查看本轮完整 Workspace。刷新页面可恢复当前会话的成果；新一轮语音会话不会沿用上一轮的成果。Workspace 服务不可用时，语音及后台任务仍可使用，结果仍在任务列表中；启动 Workspace 后重新开始一轮对话即可关联。

本轮验证覆盖真实浏览器页面、Workspace HTTP/WebSocket 和模拟任务结果的展示链路；不代表重新完成了真人语音、模型任务或 Zoom 验收。


展示由前台 Realtime 控制：可以说「展示刚才那份天气报告」「换成上一份文档」「先收起来」。Realtime 先查询当前会话的成果目录，再调用展示或收起工具；仅展示已有成果不会重新委派给 Devin。Devin 继续负责生成和修改文档。前端也保留手动选择和下载。

生成动画由实际任务的排队/执行状态驱动，不表示文档已经生成，也不伪造百分比。新成果就绪不会自动盖掉正在讨论的文档。已结束的旧语音会话需要重新开始，才能加载新增的 Realtime 工具和提示词。

## Zoom 中使用 Artifact（macOS Realtime）

Zoom Realtime 与纯语音页共用预先命名、Markdown/图片交付以及展示/收起工具。
Zoom 共享原来的完整 artifact workspace 前端，不再使用简化 `/present` 页面。先在单独终端运行 `npm --prefix frontend run dev`（默认 5178，前端与 Zoom 进程需使用相同 `SPARKIE_WEB_PORT`），然后启动以下服务。更新后需重启已有 workspace 服务和 Sparkie 会话，否则运行中的进程仍使用旧协议与工具：

```bash
# 拉取更新后，先用已配置的本机 SDK 重建原生接收器；不要跳过这一步。
uv run --frozen python scripts/zoom-sanity.py build --platform macos
# 终端一：保持成果服务运行。
uv run --frozen sparkie workspace --host 0.0.0.0 --port 8790 --worker devin
# 终端二：使用已有 Zoom / Deepgram / Realtime / Devin 登录配置启动。
SPARKIE_TASK_BACKEND=devin ZOOM_PLATFORM=macos \
  bash scripts/zoom.sh --language en-US --seconds 3600 --response-mode realtime
```

默认成果服务地址为 127.0.0.1:8790；分机部署时把 SPARKIE_WORKSPACE_SERVER 设置为
Zoom 运行机器可访问的 host:port。ZOOM_MACOS_SDK_PATH 需指向实际存在的 SDK 源目录。
会话连接 Workspace 后，会加载完整前端并请求 SDK 外部共享源，截取自有 WebView 推送画面。
主持人需允许共享；只有外部共享源失败后退回 app-window 采集路径才检查 macOS 录屏权限。
Linux 与旧 wake/qa 路径未接入这套共享。

远端验收时分别说 “Sparkie, create a weather report”、
“Sparkie, plot a weather chart”、 “Sparkie, show the report” 和
“Sparkie, hide it”。检查等待卡片是短名称、Markdown 没有重复包装、图片可见、
切换与收起同步，而且其他任务完成不会抢占当前画面。

诊断先查看 workspace_linked、zoom_share_requested、zoom_share_state，再看 artifact_control
的确认。blocked / window_invalid / share_failed 不算共享成功；sharing 仅表示 SDK 接受，
最后仍须另一参会端确认画面。共享页可单独打开
`http://localhost:5178/workspace.html?workspace_id=<workspace_id>&server=127.0.0.1:8790` 排查渲染。
说 “Sparkie, go back to the main artifact page” 应调用 hide_artifact 返回完整列表，不停止共享、
不删除文档，也不委派后台任务去修改项目首页。界面 Back/Esc 也可退出全屏，迟到的加载不得重新打开。

本次完成了离线 Zoom 路由和工具集成、实际浏览器共享页验证，以及原生编译/链接检查。
未启动真实 Zoom 会议，未验证远端可见性、共享授权与音频延迟。自动命名提示词在新会话生效。
