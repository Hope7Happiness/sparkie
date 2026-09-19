# Realtime 本地验收

网页唯一入口 `/`：浏览器收音/播放 → Realtime 实时对话，同时 → Deepgram 人类转写；Codex 异步执行工具任务。Zoom 已通过同一会话入口接入，见下文；本轮仅完成离线验证。

## 运行

配置 `.env` 中 OPENAI_API_KEY、DEEPGRAM_API_KEY；后台复用 Codex CLI 登录和已有工具配置。

```bash
bash scripts/web.sh
# http://127.0.0.1:5178/
# 并行开发端口：
SPARKIE_WEB_PORT=5179 bash scripts/web.sh
```

点击「开始对话」后浏览器申请麦克风权限。默认英语转写；中文在设置中选择。网页要求浏览器回声消除并校验 track settings，不再要求扬声器播放期间按按钮才能打断。麦克风经同一个 AudioWorklet 连续送给两个 provider，AI 回复使用其自身输出文本。原 PortAudio CLI 仍可用，其扬声器模式是旧的半双工保护。

## 委派和工具权限

前台遇到复杂分析、搜索、文件、代码或外部操作请求应自动 delegate_task；返回任务编号后立即继续聊天。后台完成或失败后会主动唤醒前台，由前台决定汇报或保持安静；结果也显示在页面，可口述询问或点播报。后台一次处理一个任务，其他任务排队，前台不阻塞。

按用户明确授权，后台加载既有 Codex 配置、技能与工具，使用实际项目工作目录，开放 shell、网络和文件读写，关闭沙箱和审批；移除原来的每任务 90 秒超时与每会话八项任务上限。服务集成仍需要自身已安装和登录。语音 OPENAI_API_KEY 不传入 Codex，以保持 CLI 登录计费。原固定回复/旧 Q&A 模式的隔离规则不受影响。

后台读取委派时的完整转写文件，包括覆盖缺口与生成的助手文本；当前口述可能比 Deepgram 更快，由前台把完整请求一起传入。会话结束或主动取消会终止运行中的任务。原始音频不会保存；转写、任务和结果在 output/realtime/ 下。

## 验收

1. 正常问答；AI 说话时直接开口，检查停止播放并听取新请求，且不被自身声音误触发。
2. 说“查一下最新的 Zoom SDK release notes”，应出现后台任务，而非回答无法联网。
3. 任务运行中继续说“先讲个笑话”，前台应即时回复；之后保持安静，验证任务完成会唤醒前台并汇报结果。要求“完成后先别说”时应保持安静。
4. 请求创建一个测试文件，核对实际文件和后台结果；取消任务应真的停止进程。
5. 点「静音」停止麦克风输入，AI 仍可播放；取消静音恢复收音。结束或关闭页面后麦克风停止。按转写语言选择中文/英文；固定中文识别英语会明显退化。

## 已验证与待验证

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
ZOOM_PLATFORM=macos bash scripts/zoom.sh --language zh-CN --seconds 3600
```

需要 `OPENAI_API_KEY`（Realtime）、`DEEPGRAM_API_KEY`（并行转写）、既有 Codex CLI 登录和 Zoom 配置。默认 Realtime 模型沿用 `OPENAI_REALTIME_MODEL`，后台沿用 `CODEX_MODEL`。不会用固定 “I'm here.” 代替语音 agent，也不会调用 Deepgram TTS。`--response-mode wake` 仅用于诊断。

主持人接纳 Sparkie、允许录制权限，看到 `listening_ready` 后：

1. 从另一台参会设备问一个普通问题，确认听到与问题相关的自然语音回答。
2. 请它调研一个需要外部信息的问题，检查出现 `background_task`，状态由 queued/running 进入 completed 或 failed。
3. 后台进行中继续提出普通问题，确认前台可以响应；等后台完成后，检查结果通知及语音汇报。以来源/实际产物核对结果，不只看“完成”文本。
4. Ctrl+C 结束，确认 Sparkie 离会、后台任务停止；检查 `output/zoom/<session>/` 中的 transcript.jsonl、tasks.json、events.jsonl 和 run.json。

本轮不启动真人会议。Zoom 仍沿用播放及后 350ms 的回声静音保护，期间的发言不会进入 agent，也不支持该窗口内语音打断。流式输出以 100ms 包提交（包内由 SDK 桥按 20ms 发送）；提交进度不等于另一端听到的时间，真实延迟、音质及并发体验仍需上述验收。浏览器入口保持现有 AEC 和语音打断行为。


### 终端输出背压修复

本地会话 `20260919T171253-ac5d40a5` 在 107742ms 的 `BlockingIOError` 紧跟播放事件输出，随后 5100ms 播放等待超时。该时刻 SDK 日志已完成第 335 包发送，收音仍持续；Python 队列最大仅 3 帧。以写满的真实伪终端复现：同步 stdout 打印抛错，中断接收循环，已到达的播放完成确认未被处理；错误日志自身再次抛错还会跳过原来的清理。

现在 stdout 通过 `EventOutput` 有界异步队列输出，支持部分写入、EAGAIN 等待和断管处理。CLI 终端长期堵塞时只省略终端副本，完整事件仍先写 events.jsonl；run.json 的 event_output 记录省略数量和输出错误。网页 stdout 承载音频协议，不能省略，溢出会明确失败。音频接收异常会先唤醒播放等待者并停止采集，再输出诊断，避免第二次超时掩盖原始错误。

已做真实伪终端/管道的离线回归；仍需真人重跑原场景确认，不将离线复现等同于整场会议稳定性验收。本修复不改变模型、音频采样率或 Zoom SDK 配置，无需重建原生程序。

Zoom Realtime 的 --seconds 范围为 1–3600 秒，从 listening_ready 开始计时；建议会话使用 --seconds 3600。到期记录 session_duration_elapsed / exit_reason=duration_elapsed，正常退出（也会结束尚未播完的回复）；Ctrl+C 仍为 stopped。播放期间及尾音 350ms 人声会静音，不支持语音打断；可用终端 interrupt 控制取消。

### Interrupting without losing task results

The terminal still accepts one JSON command per line: {"action":"interrupt"} stops all queued output and waits for the next user turn. In Zoom speaker mode, the mixed microphone remains echo-gated while Sparkie speaks; interruption during that window requires this control or a trusted separated-human producer.

A separated-human producer can send human_turn/start immediately and human_turn/commit with final text after the user finishes. This selects external-text input for the session; all later turns must use those controls. See [the control contract](interfaces.md#semantic-interruption-and-trusted-human-controls) for examples, delivery acknowledgements and integration boundaries. Speaker separation itself is not implemented here.

Task results whose announcements are cut off remain pending for fresh generation after the user's turn. Generated or SDK-submitted speech is never marked heard automatically. Fully submitted, uninterrupted announcements remain unconfirmed without repeatedly waking the agent; explicit human confirmation prevents later automatic reannouncement.

Focused offline validation: uv run --frozen python -m unittest discover -s tests -p test_semantic_interruption.py -v. These tests use a fake audio bridge and WebSocket and provide no live audibility evidence. Native cancellation protocol is unchanged; no SDK rebuild is required for this feature.

### Zoom 默认输出静音（当前 MVP）

以上 Zoom 普通问答步骤现在需要句首点名，例如 “Hey Sparkie, explain the architecture in detail”。只关闭 Sparkie 的 Zoom 输出；Realtime 会话/输入上下文、Deepgram 和 Codex 后台任务持续运行。未点名的普通会议发言进入现有 Realtime 上下文，但不会触发无必要的助手生成。浏览器/local 模式不变。

使用原有 Sparkie/Sparky（可带 Hi/Hey/Hello）最终转写唤醒；完整回答和所属工具续答结束、队列排空后自动静音。没有 12 秒或其他产品发言时长截断；保留有界音频积压保护及会话总时长。授权请求产生的后台任务，其结果通知可以单独唤醒输出；其他任务不能。

终端每行一个 JSON：{"action":"mute"} 停止并清空全部播放，不取消后台任务；{"action":"unmute"} 仅允许下一条最终人类转写触发一条回答链，不恢复旧音频。也可说 “Sparkie, stop” / “不用了”等既有取消词；播放期间 Zoom 混合输入仍受回声门控，需终端或可信分离人声控制实现该窗口内取消。普通混合 VAD 不再自行打断 Zoom 回答，最终文本负责 wake/cancel。

测试时分别核对：未点名讨论零输出；长回答完整；自动重新静音；后台任务归属；mute/unmute 不复活旧音频。使用同一会话观察输入/转写持续。SDK 提交不代表远端听到；需另行真人验证最终转写延迟、音质、停播残留和误唤醒。完整契约见 interfaces.md 的 Zoom output mute MVP。
