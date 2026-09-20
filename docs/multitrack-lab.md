# 本地双人讨论转写测试

启动命令：bash scripts/web.sh。打开 http://localhost:5178/multitrack.html；语音首页“设置 → 双人讨论测试”也可进入。服务端需要 .env 中的 DEEPGRAM_API_KEY，默认模型 nova-3，默认识别语言 English。

## 使用

1. 点击左侧或右侧麦克风直接开始，以这一侧的身份发言。“开始讨论”默认启用左侧。
2. 点击另一侧自动切换发言身份，原来一侧立即静音。同一时间最多启用一侧；再次点击已启用的麦克风，两侧全部静音。
3. 下方左右两栏分别显示两人的实际转写。设置中可更改显示名、识别语言和使用的物理麦克风；同名仍按两个独立 ID 区分。
4. 点击“结束讨论”释放麦克风，并等待最后的转写。讨论无固定时长上限，静音期间仍可随时点击任一侧继续。已完成或中断的记录均可导出。

两个按钮共用同一只真实麦克风，适合一个人切换身份模拟轮流讨论，不是两个物理输入设备，也不能模拟同时说话。麦克风需要 localhost 或可信 HTTPS。页面沿用原语音前端样式，但只调用真实 Deepgram 进行转写，不加入 Zoom、不调用 Realtime 或 Devin，不提供离线假转写。

## 音频与结果

浏览器持续采集为 32 kHz PCM16，每 20 ms 发出两路帧；当前身份使用真实音频，另一条填零，全部静音则两路都填零。切换会丢弃至多一个未完成的 20 ms 片段及已排队的旧身份帧，避免把上一人的话写到下一人名下；建议说完一句后再切换。

Python 使用生产 ZoomMacAudioMeeting 的 U 帧解码/独立队列及 ParticipantEars 分流器，每位活跃参会者独立连接 Deepgram。切换身份不重启整场会话；识别流按生产路由器的静音策略关闭和重开。显示时间来自词尾在整场讨论中的位置，不能当作识别延迟。服务器产物保存在 output/multitrack/<session>/，包含 transcript.jsonl、events.jsonl、run.json，不保存原始音频。

输入积压、设备失联、转写失败或连接断开会明确结束会话并保留已收到的文本。关闭页面会释放麦克风与本轮后端进程。真实 Zoom 入会、回声与会议表现仍需另行验收。

## 验证

AudioWorklet 单元测试验证半帧切换不串音、全静音、恢复及停止。运行回归：uv run --frozen python -m unittest discover -s tests -v、npm --prefix frontend test、npm --prefix frontend run build、bash scripts/primitive.sh、bash scripts/demo.sh。primitive/demo 是既有离线回归，不作为真实识别证据。

2026-09-19 当前界面验证：204 项 Python 测试、20 项前端测试、构建与两个回归脚本均通过。浏览器中将两条固定英文音频接入 MediaStream 后，实际经过页面 AudioWorklet → WebSocket → 生产分轨路由 → 真实 Deepgram；左→右→左三次分别得到 bicycle / apple / bicycle 原句，身份正确。全静音期间两路 PCM 都为零，未出现同时启用或送错身份的帧；结束时最后一句完整排空，媒体轨道停止。产物：output/multitrack/20260919T213241-1fb1ab66/。这是固定音频注入测试，不是声学识别证明。

另用原生麦克风及扬声器回放验证了设备采集、左右互斥、全部静音、超过原 95 秒连接上限后仍可继续、结束释放设备及再次点击右侧重启。右侧 apple 原句正确识别，但这轮左侧 bicycle 未正确识别，因此不宣称完整声学识别验收通过；记录在 output/multitrack/20260919T212954-d8850bce/。390 px 视口保持左右麦克风且无横向溢出。

之前文件音轨界面的两路/四路真实 Deepgram 验证记录保存在 output/multitrack/20260919T211829-c04e1f85/、20260919T211833-6d4466d8/ 与 20260919T212056-4a32f267/；这些只证明之前的分轨输入链路，不能替代当前实时麦克风界面的验收。
