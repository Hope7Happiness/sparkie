# 本地多音轨转写测试

启动 `bash scripts/web.sh`，打开 http://localhost:5178/multitrack.html；语音首页“设置”中也有入口。需要服务端 `.env` 的 DEEPGRAM_API_KEY；默认模型 nova-3，默认识别语言 English。

本页只模拟参会者输入并调用真实 Deepgram，不加入 Zoom、不调用 GPT Realtime 或 Devin，也不提供假转写/离线模式。单路 Realtime 混音由正式会议入口处理，与此页面独立。

## 操作

1. 默认加载两路英文合成语音；点“开始测试”可同时发送。也可以分别上传浏览器支持的音频文件或点击“录制音轨”。录音在本机完成，开始测试后才发送音频。
2. 为每条音轨填写名字及起点偏移。最多四路，每轮含偏移最多 60 秒。允许同名；身份由独立的 zoom:1、zoom:2 等模拟 ID 区分。录音需要 localhost 或可信 HTTPS。
3. 可选择同时从扬声器回放。回放只供听音核对；提供者输入来自独立音轨 PCM，不从扬声器重新采集。
4. 查看分轨文本及时间。语音时间是 Deepgram 词尾时间加音轨在共同时间轴上的偏移；“收到于”是浏览器收到结果距本轮开始的时间，不是精确识别延迟。
5. 停止会结束这一轮输入及连接，已显示文本保留但可能不完整。正常完成后可导出完整结果。服务器产物在 output/multitrack/<session>/，包含 transcript.jsonl、events.jsonl、run.json；不保存输入录音。

## 测试边界

浏览器先把每路音频解码为 32 kHz 单声道 PCM16，按统一时钟每 20 ms 发送一组分轨帧。Python 使用生产 ZoomMacAudioMeeting 的 U 帧解码/独立队列和 ParticipantEars 分流器，每位活跃参会者独立连接 Deepgram；不会生成或转写混音。每个连接最多一轮，当前服务一次允许一轮多轨测试；输入积压、提供者错误、断开或超时明确结束，不伪造结果。

2026-09-19 浏览器真实链路验证：两路示例完全重叠时，分别得到 bicycle / apple 原句，身份对应 zoom:1 / zoom:2；改为相同显示名且第二路偏移 1 秒后，两条文本仍正确隔离，第二路词尾时间由 1840 ms 变为 2840 ms。证据保存在本机 output/multitrack/20260919T211829-c04e1f85/ 与 20260919T211833-6d4466d8/。这些是浏览器模拟输入到真实 Deepgram 的结果，不是 Zoom SDK 入会或真实多人会议验证。

同日补充验证：通过浏览器上传四路音频并同时发送，四个独立 ID 均得到各自正确文本（output/multitrack/20260919T212056-4a32f267/）；中途停止后可重新开始。浏览器本机麦克风录制约 1 秒后成功生成音轨，停止后媒体轨道状态为 ended；此项只验证录音与释放资源。390 px 宽视口无横向溢出。

运行回归：`uv run --frozen python -m unittest discover -s tests -v`（204 项通过）、`npm --prefix frontend test`（18 项通过）、`npm --prefix frontend run build`、`bash scripts/primitive.sh`、`bash scripts/demo.sh` 均通过。单元测试中的替身提供者只验证错误清理和路由隔离；primitive/demo 是原有离线回归，不作为真实识别证据。
