# Realtime 本地验收

网页唯一入口 `/`：浏览器收音/播放 → Realtime 实时对话，同时 → Deepgram 人类转写；Codex 或 Devin CLI 异步执行工具任务。Zoom 传输仍由独立改动接入。

## 运行

配置 `.env` 中 OPENAI_API_KEY、DEEPGRAM_API_KEY；后台复用所选 CLI 的登录和已有工具配置。

### 选择 Devin 低延迟配置

后台提供者由独立的 `SPARKIE_TASK_BACKEND` 选择，默认 `codex`；旧问答入口的 `SPARKIE_BACKEND` 不受影响。Devin 使用本机 CLI，不创建 Devin Cloud 会话。先安装并登录 Devin，再在 `.env` 设置：

```dotenv
SPARKIE_TASK_BACKEND=devin
DEVIN_MODEL=swe-1-6-fast
```

用 `devin auth status` 核对登录，`devin models list` 核对当前账号的模型 UID。`swe-1-6-fast` 是本机 CLI 3000.10.31 已列出并实测的型号；其他账号的可用性需自行核对。配置只影响新会话，结束当前对话后重新开始。切回 Codex 使用 `SPARKIE_TASK_BACKEND=codex`。

Devin 使用常驻的 ACP 标准输入/输出连接。每次语音会话启动时并行初始化一个 CLI 进程和一个 agent 会话，不阻塞前台语音连接；之后的后台任务、追问和修改都复用该进程与上下文。使用现有登录、工具配置和项目目录，保持无审批权限，不设置单任务超时。启动握手有 60 秒上限，失败只影响后台；不会静默切换成另一个无上下文的 agent 或自动重放任务。

前台可持续调用 delegate_task、task_status、update_task、cancel_task。update_task 接收**完整修订后的请求**：排队任务直接更新，运行中的 Devin 任务先通过 ACP 取消当前轮，再在同一会话送入修改。返回 pending 只表示接收排队；applied_revision 和 update_delivery=delivered 表示已写入后台连接，不表示任务完成。已经发生的文件或外部操作不会撤销。普通取消保留 agent 会话供下一轮使用；5 秒未确认取消则终止进程组，并拒绝在失去上下文后静默继续。

「结束对话」、关闭页面或音频连接断开会关闭该 agent 进程组；下次「开始对话」建立新会话。目前不跨语音会话恢复。转写快照放在会话专用临时目录，保留到会话结束，便于后续轮次引用。CLI 自己仍可能保存会话历史。语音 OPENAI_API_KEY 不转发给 CLI。

会话记录 task_backend_starting / task_backend_ready / task_backend_failed，任务记录 agent_session_id 和 agent_pid 便于核对是否复用。任务卡片显示模型与工具阶段；只提取 ACP 工具类型、状态和公开回答，不展示思考内容、原始命令输出或凭据。

2026-09-19 真实验证：同一进程与同一 ACP 会话连续四轮，启动 4.55 秒；记住随机测试内容 2.92 秒；依据上一轮记忆创建并核验文件 3.83 秒；运行中修改等待任务后 1.49 秒返回新结果；最后追问原内容 0.84 秒。独立读回文件核对内容，结束后进程已退出。这是后台任务实测，不是语音端到端延迟或受控性能对比；旧 print 模式的一轮完整任务曾耗时 39.2 秒。简单桌面文件/打开网址仍优先走本机直接工具。模型依据：[Devin 模型说明](https://docs.devin.ai/cli/models)和当前账号 CLI 列表。

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

简单的桌面文本文件创建使用 `create_desktop_file`，打开指定网址使用 `open_website`，直接调用本机能力并显示任务结果，不进入后台队列。创建文件不会覆盖已有文件；打开网址只确认默认浏览器接受请求，不声称网页已加载。网页检索、复杂内容生成、其他文件/代码操作仍通过 delegate_task 交给所选后台。

后台完成或失败后会主动唤醒前台，由前台决定汇报或保持安静；结果也显示在页面，可口述询问或点播报。后台一次处理一个任务，其他委派任务排队，前台和简单本机操作不受该队列阻塞。Codex JSON 与 Devin ACP 事件提供当前工具阶段。用户补充任务信息时，通过 `update_task` 更新原任务；Devin 支持运行中修订，其他后端仍只支持排队中更新。

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
- 2026-09-19：复现旧版后台串行排队与 `audio-stalled` 六秒强制停止。完整 Codex 小文件对照任务耗时约 41–90 秒；新增本机文件工具独立执行并核验约 21 ms，真实 Realtime 文本指令选择该工具后完成文件创建，连接就绪至任务完成约 0.7 秒。测试文件已清理；此数据不等于真人语音端到端延迟。
- 浏览器合成静音输入经真实提供者连接：暂停 AudioContext 超过六秒后会话仍保留，点恢复后继续输入，显式结束正常退出。没有用合成流代替真人收音验收；底层输入停顿原因尚未确诊。

- 真实 Codex worker 已调用 shell 写入并读回测试文件，验证不止是提示词声称具有权限。
- 真实 Realtime 自动把“查最新 release notes”交给工具；控制为未完成的后台任务运行时，前台继续回答下一轮中文问候。此测试验证委派/并发，不冒充完成真实网页研究。
- 浏览器真实 AudioWorklet 合成输入测试：24 kHz、480 samples/包，并报告支持 echoCancellation；没有打开用户麦克风。实际 track 设置会在正式开始时校验，扬声器回声效果和自然语音打断需真人验收。
- 真实本地 WebSocket → Python → provider 连接以合成静音验证，非真人收音测试。
- 真实 Realtime 已通过固定后台测试结果验证自动汇报与 remain_silent 两种选择；这不代表真实 Codex 任务在该测试中执行。
- 单元测试覆盖输入持续采集、输出清空、旧 generation 丢弃、任务取消、转写持久化及回复续接。

参考：[浏览器回声消除](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackSettings/echoCancellation)、[Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations)。
