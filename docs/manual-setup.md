# 人工配置清单

当前采用[一人编码、两人测试反馈](team-first-steps.md)；本清单不再分配固定模块负责人。

核验日期：2026-09-19。Deepgram key 已通过真实 TTS→流式 STT 检查；本机 Codex CLI 已通过真实上下文回答测试；OpenAI key 的模型列表请求返回 HTTP 200。未检查账号余额或套餐。默认模拟原型不发起外部请求，显式 live 检查会消耗对应服务额度。

| 配置责任 | 服务 | 人工动作 | 放入本地 `.env` |
| --- | --- | --- | --- |
| 账号持有人配合当轮编码负责人 | Zoom | 开发者账号、General App、开启 Meeting SDK、下载匹配架构的 Linux SDK | `ZOOM_CLIENT_ID`、`ZOOM_CLIENT_SECRET`、`ZOOM_SDK_PATH` |
| 账号持有人配合当轮编码负责人 | 测试会议 / 环境 | 由应用所属账号主持；准备会议号密码；允许入会、录制权限与麦克风；启动 Docker | `ZOOM_MEETING_ID`、`ZOOM_MEETING_PASSWORD` |
| 当轮编码负责人 | Deepgram（已配置） | STT / TTS 共用现有 key；真实英文检查已通过 | `DEEPGRAM_API_KEY` |
| 当轮编码负责人 | Codex / OpenAI | 默认复用本机 Codex 登录；OpenAI API key 已配置，切换 API 时另填模型 | `SPARKIE_BACKEND=codex`；可选 `OPENAI_MODEL` |
| 当轮编码负责人 | Deepgram TTS | 选择声音和英文回复，无需额外 ElevenLabs 账号 | `DEEPGRAM_TTS_MODEL`、`SPARKIE_REPLY` |

## Zoom 是关键路径

以下编号步骤描述 Linux Docker 路径。macOS SDK 用户按 [macOS 原生探针](zoom-macos.md) 配置 `ZOOM_PLATFORM=macos` 与 `ZOOM_MACOS_SDK_PATH`，无需 Docker；`doctor` 会按所选平台检查依赖。两者共享 Zoom 凭证。

1. 登录 [Zoom App Marketplace](https://marketplace.zoom.us/)。账号需为 owner/admin，或有 Zoom for developers 角色及 SDK View/Edit 权限。
2. 创建 **General App**，在 **Features → Embed → Meeting SDK** 开启功能，保存应用的 Client ID 和 Client Secret。不要拿 Server-to-Server OAuth 凭据替代 Meeting SDK 凭据。
3. 在 Meeting SDK 下载页选择 Linux 并下载；解压目录应包含 `h/`、`libmeetingsdk.so` 等文件。`ZOOM_SDK_PATH` 填解压后的绝对路径。商业 SDK 文件不提交仓库。[创建应用与凭据](https://developers.zoom.us/docs/meeting-sdk/get-credentials/)、[Linux 下载说明](https://developers.zoom.us/docs/meeting-sdk/linux/get-started/download/)
4. 首次只用**应用所属 Zoom 账号主持**的测试会议。文档说明这种场景可以仅用 SDK JWT 入会；JWT 后续由程序生成。不同人的同名组织、MIT 邮箱或同一团队不自动等于同一个 Zoom account。[授权规则](https://developers.zoom.us/docs/meeting-sdk/auth/)
5. 主持人启动会议、在等待室接纳 Sparkie，并批准 SDK 请求的本地录制权限。原始音频订阅需要 host/co-host/local-recording rights 或相应 recording token；仅“成功入会”不代表已经收到音频。主持人还需允许使用麦克风。[Zoom 官方原始音频示例](https://github.com/zoom/meetingsdk-linux-raw-recording-sample)
6. 启动 Docker。当前开发机为 ARM64；Zoom 文档说明 Linux SDK 7.0.0 起支持 ARM64，但必须下载匹配包，不能把旧 x86 示例直接当作 ARM 方案。官方明确不推荐 QEMU/Rosetta 跨架构运行。[Linux 环境要求](https://developers.zoom.us/docs/meeting-sdk/linux/get-started/download/)

**跨账号入会是后续配置：** 应用需要 Zoom 审核，并采用适用的 ZAK/OBF 用户授权；OAuth、相关 scopes、用户安装授权以及 token 获取都要按该流程配置。不能仅给一个任意会议链接就假定 bot 可进入。[Zoom 入会授权](https://developers.zoom.us/docs/meeting-sdk/auth/)

## Deepgram 与 OpenAI

Deepgram：在 [Console](https://console.deepgram.com/) 建立项目并生成 API key，确认账户有测试额度。程序使用 `Authorization: Token ...` 连接流式服务。当前预设 Nova-3、`zh-CN`；英文 demo 改为 `en`。中文和中英混说的实际识别率需要测试，不能仅凭支持语言列表保证效果。[认证](https://developers.deepgram.com/guides/fundamentals/authenticating)、[流式转录](https://developers.deepgram.com/docs/live-streaming-audio)、[语言支持](https://developers.deepgram.com/docs/models-languages-overview)

OpenAI：在 [API Platform](https://platform.openai.com/) 创建项目 API key，确认可调用的模型、用量限制和 API 额度。`OPENAI_MODEL` 填项目实际可用的模型 ID，不默认假定权限。首个固定“我在”闭环不调用 OpenAI；该 adapter 用于下一阶段上下文问答。[官方 quickstart](https://developers.openai.com/api/docs/quickstart)

## Deepgram TTS

STT 和 TTS 共用现有 Deepgram key。当前使用 `aura-2-thalia-en`，请求 `/v1/speak`，输出无容器的 PCM16 mono 32kHz，再保存为 WAV 或交给会议音频层。固定回复为 **I'm here.**。已用真实 key 生成 `output/deepgram/reply.wav`，不再要求 ElevenLabs API key 或 Voice ID。[TTS 接口](https://developers.deepgram.com/docs/text-to-speech)、[输出格式](https://developers.deepgram.com/docs/tts-media-output-settings)

Deepgram 官方 TTS 支持列表目前没有中文；Aura-2 列出英、西、德、法、荷、意、日七种语言，Flux TTS 当前为英文。本原型先用 Aura REST 固定短句，STT 的 `zh-CN` 配置保留。**中文语音识别能力不代表支持中文语音合成。** 英文模型收到中文回复会明确报错，不静默输出错误读音。[TTS 语言列表](https://developers.deepgram.com/docs/tts-models-languages-overview)

## 本机 Codex 后端

`SPARKIE_BACKEND=codex` 是当前默认推理后端。本机 `codex-cli 0.153.4` 已使用 ChatGPT 登录，并已完成一轮上下文回答测试。程序通过 `codex exec` 非交互调用，stdin 输入上下文，最终文本从临时文件读取；无需项目的 OpenAI API key。CLI 仍会连接云端，并受 Codex 账号用量限制，不是离线模型。[官方非交互模式](https://developers.openai.com/codex/noninteractive)

该 adapter 使用独立临时目录、read-only sandbox，禁用 shell 与 web search，忽略用户运行配置但保留 CLI 登录；不会把 Deepgram/OpenAI key 传入子进程。它目前只回答给定会议上下文，不执行搜索、文件编辑或其他外部任务。空 `CODEX_MODEL` 使用 CLI 默认模型；`CODEX_TIMEOUT_SECONDS=120`，超时和取消会结束子进程。

切换 OpenAI API 时设置 `SPARKIE_BACKEND=openai` 并填写 `OPENAI_MODEL`。现有 key 已通过只读认证检查，但尚未选择模型或执行 API 推理。默认固定回复流程不调用任何 brain；`brain-check` 才会显式调用所选后端。

## 填写与检查

首次创建 `.env`（已有文件时不要覆盖）：

```bash
cp -n .env.example .env
chmod 600 .env
uv sync --frozen
uv run --frozen sparkie doctor
```

用编辑器填写 `.env`；不要把 key 发到聊天、截图、issue 或 Git。doctor 仅报告配置是否存在、SDK 文件和 Docker 状态，不显示值，也不验证云端有效性。缺配置会返回退出码 1，**不影响 simulate**。

大家完成后同步“哪项已完成”和 SDK 版本/架构即可。真实会议接入尚需实现原生 adapter，并在上述配置就绪后编译联调；不承诺填入 key 后当前模拟 CLI 会自动变成 Zoom bot。
