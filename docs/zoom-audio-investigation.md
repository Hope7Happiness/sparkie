# 音频开头失真与接收积压调查（2026-09-19）

## 2026-09-20：入会 connecting 卡住的独立问题

用户报告会话 20260920T100219-3aebb78b：SDK 初始化与认证成功，入会一直为 connecting，120 秒后 connecting_timeout，正常退出再等 10 秒仍未完成。会议确实在进行，用户确认当时无权限弹窗。09:26 的成功会话使用同一个昨晚构建的原生程序；本机 .env 也早于成功会话且未更改。不能仅凭发生在 git pull 后就归因于新共享代码。

以同一已安装程序做仅入会/音频诊断，在 .runtime/zoom-join-diagnostic/20260920T140602Z 复现。3 秒线程采样中，主线程持续位于 Zoom viper → AudioDeviceStart_mac_imp → HALC_ProxyIOContext::_StartIO → HALB_IOThread::_WaitForState → mutex wait。与 Zoom 服务端的 TCP/UDP 连接已经存在，但不能据此宣称所有网络路径正常。已证实的阻塞位置是 CoreAudio 设备启动，不是 Gemini 唤醒、转写或成果共享。原有主线程退出处理也因这一阻塞不能及时运行。为何此次设备启动阻塞、此前却正常，触发条件尚未查明。

语音模式现在关闭 enableAutoJoinVoip，并以 isNoAudio=YES 请求入会；在 InMeeting 回调中先安装虚拟麦克风，再显式 JoinVoip / UnMuteAudio。接收探针保留原设置，不更改系统默认设备、不重启 coreaudiod。编译后的原生程序已安装到本机现有 app 路径。

重建后首次启动另遇钥匙串授权：线程位于 SecItemCopyMatching，属于 SDK_INIT 阶段，和原始 CoreAudio 阻塞不同。用户处理后，诊断 20260920T140810Z 到达等候室；用户接纳后依次出现 InMeeting、AUDIO_SOURCE_SET result=0、JOIN_VOIP result=0、ZOOM_MIC_READY、START_RAW_RECORDING result=0、AUDIO_SUBSCRIBE result=0，Python join() 成功，最后 RECEIVER_STOPPED exit=0。该次真实复测证明调整后的程序完成入会和双向音频通道就绪；没有启动 Realtime/Deepgram/后台任务，没有保存原始音频，也没有验证远端听到回复或共享画面。单次恢复不能证明系统音频死锁已永久消除。

新阶段诊断能区分 SDK 初始化未返回、音频连接调用未返回，以及音频设置失败；不会把上一条成功的 sdk_result 误挂在未返回的调用上。回归测试编译并执行真实原生认证回调（SDK 为替身），验证语音模式延后音频、接收探针兼容性和设置失败时不继续入会；Python 测试验证对应超时阶段与固定错误码。

本轮 331 项 Python 测试、scripts/primitive.sh、scripts/demo.sh 与 macOS 原生构建通过。其他机器需先用 scripts/zoom-sanity.py build --platform macos 重建；本机已完成。完整语音启动沿用 ZOOM_PLATFORM=macos bash scripts/zoom.sh --language en-US --seconds 3600 --response-mode realtime；这次仅入会诊断不替代完整语音验收。

## 以下为 2026-09-19 音频调查记录

本次修正基于 `f7bcd24`，包含突发输入调度、输出补帧节奏及诊断日志改进。首段及后续卡顿的主观音质问题仍未关闭；实测媒体链路丢包尚未解决。

## 已复现的两个代码问题

1. **突发输入时消费端得不到足够执行机会。** `StreamReader.readexactly` 在已有缓冲时可直接返回；接收循环连续 `put_nowait`，STT 发送端却为每一帧创建 task 并等待。之前的 10 ms 空队列轮询也会让突发数据赶在消费者醒来前填满队列。扩大队列没有解决根本调度问题。
   - 在合成的 4,000 帧 TCP 缓冲突发中，原路径复现 `QueueFull`；修正后 PCM 按序完整交给模拟 STT socket。
   - 本地改动：每 32 帧主动让出执行机会；空队列用可唤醒的 `queue.get`；STT 直接迭代音频，将空闲 KeepAlive 放到独立、受同一 supervisor 管理的任务中。队列仍有 1,000 帧上限；慢服务造成持续积压时仍报错，不静默丢帧。
   - 日志新增已消费帧数、队列深度与最大接收间隔。接收间隔不能单独区分 Python 调度、Docker、TCP 或 Zoom 网络的原因。
2. **输出线程错过节拍后快速追赶。** 原生桥一直累加固定 deadline；线程或 SDK 停顿后，多个 deadline 已经过期，`sleep_until` 会立即返回。
   - 真实基线第一遍 512 帧中出现 71.97 ms 最大间隔及 3 次小于 5 ms 的间隔；第二遍最大 31.61 ms、无小于 5 ms 的间隔。
   - 本地改动：当发送时刻已经晚于下一 deadline，重新从实际发送时刻安排下一帧，避免连续追赶。增加每次播放的帧数、最大/最小间隔、前两秒最大间隔与 SDK 调用耗时日志。
   - C++ 回归测试直接运行真实播放循环，仅替换 SDK sender，让第三次调用阻塞 75 ms：旧代码以退出码 4 复现快速补发；修正后保持全部 PCM 并通过。这个测试不是 Zoom 网络或主观音质验证。

## 同源真实会议录音

两轮都复用 `output/zoom-quality/source.wav`（10.240 s、32 kHz、单声道 PCM），连续播放两遍，中间停 5 s；不重新合成。接收端使用 AudioWorklet 在 48 kHz 音频线程捕获，检查渲染帧编号；两轮均未发现采集块编号缺口。主持端只有合成静音麦克风，无真人音频录制。

- 基线：`output/zoom-quality-investigation/baseline-twice.wav`。
- 本地修正：`output/zoom-quality-fixed/fixed-twice.wav`。
- 分段近似匹配 RMS 的试听件：各目录的 `baseline-1.wav` / `baseline-2.wav` 与 `fixed-1.wav` / `fixed-2.wav`。原始录音保留；切片在语音能量阈值外留短静音，因此不同切片长度不能当作丢字证据。
- 修正后的本轮两遍最大帧间隔为 20.88 / 21.18 ms，无小于 5 ms 或大于 40 ms 的间隔。

**限制：** 两轮运行时系统负载不同；没有人为复现相同调度干扰，不能凭后轮更平稳的数值认定所有改善都是修复造成。音频线程连续仅排除了该录音器丢块，不能排除 Zoom 编解码、缓冲、网络或接收设备内部的调整。上一轮约 12 kHz 低通也不能解释随时间改善的全部现象。波形相关性不是主观音质分数。

## 真实恢复测试

本地修正运行真实 Zoom + Deepgram。会话 `20260919T191536Z-bac15a` 就绪后，将本任务的宿主 Python 进程暂停 3 秒再恢复（未暂停 Zoom 容器或其他进程），日志记录最大接收间隔 3,175 ms，随后继续接收与转录，无队列溢出。随后一次合成麦克风问题触发确认、推理与答案播放完成；转录将问题识别成 “Sparkie with the left socket.”，机器人据此请求澄清，因此不能将本轮称为正确理解原问题或音质通过。

最终完整运行 7 分钟，退出状态 `completed`，`response_failures=0`；最大队列深度 100 帧，无溢出。收到 42,133 帧、消费 42,092 帧：计时结束至连接清理期间仍有尾部输入到达，不能把这两个计数的差值当作运行中丢包。报告在本地 `output/zoom/20260919T191536Z-bac15a/run.json`。这只覆盖该长度与该干扰的测试，未验证整场长会稳定性。

本地最终验证：73 项 unittest 通过（包括原生播放循环与突发输入回归）、两条离线演示通过、Linux ARM64 SDK 镜像重建通过。此前确认语测试依赖 10 ms 的事件间隔，在系统忙时会按正常 busy 规则拒绝第三个事件；测试已改为等待上一响应结束，再验证缓存/选择行为，不修改生产 busy 规则。

## 后续：用户确认两遍仍有卡顿后的定位

另做了同源、同时双接收端测试：浏览器 AudioWorklet + 独立 Linux SDK 原始音频接收。两遍提交给发送 SDK 的间隔稳定在约 19–21 ms，但 SDK 周期统计明确报告丢包：末次发送平均/最大丢包字段为 7.2% / 16.6%，接收平均/最大字段为 9.2% / 17.3%。这是 SDK 窗口统计，不是整段总体丢包率。独立 SDK 录音同样出现分段波形时间偏移跳变，排除了“只有浏览器录音端有问题”的解释。

因此当前最明确的问题范围为 **Zoom 媒体传输与接收缓冲路径**；尚未细分 Colima 虚拟网络、Wi-Fi、上游路径或 SDK 调度的贡献。原始语音、发送调度修正、输入队列修正都不能单独解决实测丢包。没有把首段音质问题关闭，也没有修改系统代理或网络设置。详细方法、窗口统计、原始双路录音与试听件在 `output/zoom-localize/README.md`。双接收端定位实验仅在忽略目录下增加诊断脚本和镜像，未额外修改产品代码。录音、SDK 文件与临时凭证不随代码提交。

## macOS 双路输入后无唤醒回复（基于 763ac80）

真实会话 `20260919T222323-5f3c6f54` 收到了混音和用户音轨，但分轨入口队列达到 500 帧上限，随后 `transcript_degraded`，没有产出用户转写。由于 Zoom 唤醒依赖 Deepgram 最终文本，Realtime 即使检测到语音也没有获得回复授权。之后还出现桥断连；不能仅凭队列修复认定断连也已解决。

可重复的本地测试将 6,000 组 A/U 包放进生产 StreamReader，由真实分流器送给快速模拟识别器。旧代码报 `Participant input queue full`；只为两个队列添加 get_nowait 仍失败。根因是桥接收器每批处理多帧，而分流器每帧 sleep(0)，突发输入时两者吞吐不匹配。现在积压队列直接取帧，分流器每 32 帧让出执行；同源复现的入口峰值为 32 帧，全部 6,000 帧交给识别器，混音亦完整消费。500 帧容量、显式超限和轨道隔离均保留。

回归命令：`uv run --frozen python -m unittest discover -s tests -v`。本轮 220 项中 219 项通过；`test_fast_generation_longer_than_15_seconds_drains_in_full` 的 2 秒等待超时，使用 HEAD 原版生产模块单独运行也失败。`bash scripts/primitive.sh` 与 `bash scripts/demo.sh` 通过。上述合成输入测试不能作为真实 Zoom 语音通过的证据。

后续真实会话 `20260919T224045-7f63bfb7` 收到 10,092 个用户音频包，分轨队列峰值 31 帧，未再次溢出。Deepgram 最终文本为 “Hi, Sparkie. What is two”，触发 Realtime 追问完整问题，原生 SDK 开始接收回复音频。这仅证明转写、唤醒和提交回复路径工作；英文扬声器测试句未被完整转写，远端完整可听性未验证。原生播放日志中，本应 20 ms 的帧间隔多次达到 100–200 ms，调度/SDK 路径延迟仍明显。用户要求停止后退出会话，未继续验收，也未将整体会议体验标为修复。诊断运行临时将入会期限延长至 600 秒；生产默认 120 秒未改动。
