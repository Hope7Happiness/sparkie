# macOS Zoom 接收探针

保留 Linux Docker 探针，增加直接使用 macOS Meeting SDK 的原生入口。`zoom-sanity.py --platform macos` 的探针模式只做 **真实入会 → 主持人授权 → 原始音频帧 / 峰值统计**，不保存 PCM 录音。同一二进制在 `voice` 配置下运行完整语音桥：`bash scripts/zoom.sh` 在 `ZOOM_PLATFORM=macos` 时直接启动本 app 并复用与 Linux 相同的 loopback PCM 协议（见 [接口约定](interfaces.md#zoom-音频桥)）。语音模式已实现并通过 SDK 加载检查，**尚未完成真实会议收发验收**。

## 配置

需要处于已登录图形桌面的 Mac、完整 Xcode 26+（已接受许可）和官方 macOS SDK。当前编译与加载基线：Apple Silicon、Xcode 26.2、**macOS SDK 7.1.5.84750**。Linux 文档中的 7.0.5 版本限制不适用于此 macOS 包；其他版本和 Intel Mac 尚未验证。

保留 SDK 解压结构。在 repo 根目录执行 `uv sync --frozen`，用编辑器修改已有 `.env`；没有该文件时才从 `.env.example` 复制。配置如下：

```dotenv
ZOOM_PLATFORM=macos
ZOOM_MACOS_SDK_PATH="/absolute/path/to/zoom-sdk-macos-7.1.5.84750"
ZOOM_CLIENT_ID=你的GeneralAppClientID
ZOOM_CLIENT_SECRET=你的GeneralAppClientSecret
ZOOM_MEETING_ID=数字会议号
ZOOM_MEETING_PASSWORD=会议Passcode
```

路径指向包含 `ZoomSDK/ZoomSDK.framework` 的**解压根目录**。已有 Linux `ZOOM_SDK_PATH` 可以保留，两条路径互不覆盖；不设置 `ZOOM_MACOS_SDK_PATH` 时 macOS 才回退使用 `ZOOM_SDK_PATH`。建议 `chmod 600 .env`。环境变量优先于 `.env`。

两平台共用应用凭证、会议号和密码，启动时自动生成 JWT，无需在 Sample 窗口粘贴。会议号中的空格和横线会移除；邀请链接会被拒绝。密码原样传递，保留开头的 `0` 和大小写。首次使用由应用所属账号主持的会议；本入口不实现跨账号的 OAuth/ZAK/OBF 流程。

## 构建、检查、启动

```bash
# 一次性构建；修改原生源码或切换 SDK 后重新执行。
uv run --frozen python scripts/zoom-sanity.py build --platform macos

# 只测试原生库加载与 SDK 初始化，不认证、不入会。
uv run --frozen python scripts/zoom-sanity.py check --platform macos

# 主持人先启动 .env 指定的会议，再启动探针。
uv run --frozen python scripts/zoom-sanity.py start --platform macos
uv run --frozen python scripts/zoom-sanity.py logs --platform macos

# logs 中 Ctrl+C 只停止看日志。以下命令才会退出会议。
uv run --frozen python scripts/zoom-sanity.py stop --platform macos
```

`--platform` 覆盖 `ZOOM_PLATFORM`；两者都没有时仍使用 **linux**，不会因为运行在 Mac 上就改变团队现有工作流。设好 `ZOOM_PLATFORM=macos` 后可省略参数。

构建会复制 SDK 到本机 `~/Library/Application Support/Sparkie/ZoomReceivers/<项目路径摘要>/SparkieZoom.app`，并从 `.runtime/zoom-macos/SparkieZoom.app` 建立链接，避免 iCloud Documents 自动添加 Finder 属性导致签名失败。随后编译仓库里的 Objective-C 接收器，并对运行副本做本地 ad-hoc 签名。不会修改下载目录、安装系统音频驱动、要求 Apple Developer 付费账号，或提交 SDK 二进制。保留约 1.5 GB 空间供 staging 和最终 app 使用。它不是已公证的分发包，也不支持无桌面的 Linux/SSH 环境。

`start` 启动后台进程并写私有日志，但**进程启动不等于入会成功**。macOS 可能显示原生 Zoom 窗口和权限提示。SDK 初始化还可能请求访问自身的钥匙串条目；重新 ad-hoc 签名后可能需要再次由本人处理系统提示，密码只在系统窗口输入。本工具不读取或更改钥匙串权限。探针以 Sparkie 名称、关闭视频、麦克风静音的设置入会；测试时不要在原生会议 UI 中手动开启视频或取消静音。主持人在等待室接纳，并允许本地录制权限。Zoom 的录制提示用于原始音频访问；本程序只计算帧数和峰值。

## 验收

1. `SDK_AUTH_RESULT result=0`：SDK 认证回调成功。
2. `JOIN_REQUEST result=0` 仅说明请求接受；还需看到 `In Meeting Now...` 与会议中的 Sparkie。
3. 主持人允许录制后出现 `START_RAW_RECORDING result=0`、`AUDIO_SUBSCRIBE result=0`。
4. 持续出现 `ZOOM_AUDIO_FRAME_RECEIVED`；人类发言时 `ZOOM_AUDIO_LEVEL peak` 大于 0，静音后回落。
5. 执行 `stop` 后，确认 Sparkie 离开会议。

日志位于 `.runtime/zoom-macos/receiver.log`，按每次 start 重置。错误会打印 SDK 数字返回码；不会由应用代码打印凭证、JWT、会议号或密码。SDK 自己的诊断输出也可能出现在日志中，分享前仍需检查。配置文件权限为 600，stop 时删除；不要提交 `.runtime` 或 `.env`。

| 现象 | 检查 |
| --- | --- |
| SDK 文件缺失 | 确认下载的是 macOS 包，路径指向解压根目录 |
| 构建失败 | 完整 Xcode 26+、许可状态、SDK 架构；不要用 Linux 包 |
| 停在 SDK_INIT_BEGIN / check 超时 | 查看系统钥匙串授权提示；SDK 的同步初始化可能在等待本人授权，30 秒的 check 超时不表示 JWT 无效 |
| check 出现重复 Objective-C 类警告 | 本机 SDK 7.1.5 加载时观察到上游 bundle 重复类警告，但初始化返回 0；保留记录，不将它视为会议验证 |
| 再次要求密码 / 密码错误 | 对照当前会议邀请中的实际 Passcode；不是 Client Secret 或 URL 的 pwd 参数 |
| 认证请求返回 0，但没有认证回调 | 等待最多 60 秒；`SDK_AUTH_TIMEOUT` 会停止进程，不宣称认证成功 |
| 已入会但没有音频 | 看录制授权、音频订阅结果，确认主持人加入电脑音频且未静音 |
| 修改配置无效 | stop 后 start，检查 shell 中是否有旧环境变量覆盖 `.env` |

## 本次验证记录与限制

- 本机用官方 macOS SDK 7.1.5.84750 完成原生编译、签名验证；首次版本运行观察到 `SDK_INIT result=0`、`SDK_LOAD_CHECK_OK` 和正常退出。
- 后续重新签名的版本初始化检查超时；进程采样定位到 SDK 的 `SecItemCopyMatching` / 钥匙串访问等待，需本人处理系统授权后重测最终版本。未绕过或修改系统保护。
- 自动化覆盖共用 JWT、会议号处理、Linux 命令兼容、私有配置权限、macOS 子进程环境和陈旧 PID 防护；离线 primitive/demo 仍可运行。
- 用户此前已成功用官方 macOS Sample 加入会议；**这不等于本 PR 新接收器已完成真实会议与非静音音频验收**。新接收器的这些步骤仍待真人测试。
- Linux 已有实测记录见 [原有流程](zoom-sanity.md)，本次没有重新完成 Linux 真实会议验收。
- 当前 Zoom 文档对 Meeting SDK bot/AI 场景有限制，本地技术测试不代表生产或跨账号用途获准；见 [官方 SDK 说明](https://developers.zoom.us/docs/meeting-sdk/linux/) 与 [入会授权](https://developers.zoom.us/docs/meeting-sdk/auth/)。
