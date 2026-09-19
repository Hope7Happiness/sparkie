# Realtime 本地验收

网页唯一入口 `/`：浏览器收音/播放 → Realtime 实时对话，同时 → Deepgram 人类转写；Codex 异步执行工具任务。Zoom 传输仍由独立改动接入。

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

前台遇到复杂分析、搜索、文件、代码或外部操作请求应自动 delegate_task；返回任务编号后立即继续聊天。后台结果显示在页面，可口述询问或点播报。后台一次处理一个任务，其他任务排队，前台不阻塞。

按用户明确授权，后台加载既有 Codex 配置、技能与工具，使用实际项目工作目录，开放 shell、网络和文件读写，关闭沙箱和审批；移除原来的每任务 90 秒超时与每会话八项任务上限。服务集成仍需要自身已安装和登录。语音 OPENAI_API_KEY 不传入 Codex，以保持 CLI 登录计费。原固定回复/旧 Q&A 模式的隔离规则不受影响。

后台读取委派时的完整转写文件，包括覆盖缺口与生成的助手文本；当前口述可能比 Deepgram 更快，由前台把完整请求一起传入。会话结束或主动取消会终止运行中的任务。原始音频不会保存；转写、任务和结果在 output/realtime/ 下。

## 验收

1. 正常问答；AI 说话时直接开口，检查停止播放并听取新请求，且不被自身声音误触发。
2. 说“查一下最新的 Zoom SDK release notes”，应出现后台任务，而非回答无法联网。
3. 任务运行中继续说“先讲个笑话”，前台应即时回复；之后问后台结果。
4. 请求创建一个测试文件，核对实际文件和后台结果；取消任务应真的停止进程。
5. 结束或关闭页面后麦克风停止。按转写语言选择中文/英文；固定中文识别英语会明显退化。

## 已验证与待验证

- 真实 Codex worker 已调用 shell 写入并读回测试文件，验证不止是提示词声称具有权限。
- 真实 Realtime 自动把“查最新 release notes”交给工具；控制为未完成的后台任务运行时，前台继续回答下一轮中文问候。此测试验证委派/并发，不冒充完成真实网页研究。
- 浏览器真实 AudioWorklet 合成输入测试：24 kHz、480 samples/包，并报告支持 echoCancellation；没有打开用户麦克风。实际 track 设置会在正式开始时校验，扬声器回声效果和自然语音打断需真人验收。
- 真实本地 WebSocket → Python → provider 连接以合成静音验证，非真人收音测试。
- 单元测试覆盖输入持续采集、输出清空、旧 generation 丢弃、任务取消、转写持久化及回复续接。

参考：[浏览器回声消除](https://developer.mozilla.org/en-US/docs/Web/API/MediaTrackSettings/echoCancellation)、[Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations)。
