# Zoom 机器人快速配置：真实入会与音频接收

这份流程复现 2026-09-19 已通过的实测：**Sparkie 以独立参会者进入 Zoom，取得主持人许可后收到真实会议音频。** 不需要 Deepgram、OpenAI 或 TTS 配置。它是独立接入探针，尚未接入 Python `AudioMeeting`、转文字、内容理解或语音回复。

macOS 原生 SDK 用户可使用 [macOS 接收探针](zoom-macos.md)。本文继续描述已验证的 **Linux Docker** 路径；`ZOOM_PLATFORM` 默认 `linux`，切换过平台时可在 start/logs/stop 命令后加 `--platform linux`。

## 1. 准备环境与账号

已验证环境：Apple Silicon Mac、可运行 ARM64 Linux 容器的 Docker、Python 3.11+、uv、Git。先启动 Docker，再在仓库根目录执行：

```bash
uv sync --frozen
docker info
```

此流程固定使用 **Zoom Meeting SDK Linux ARM64 7.0.5.3529**。此 Docker 流程不要选 macOS SDK 或 Linux x86_64 包；Intel / Windows 环境尚未按这份流程验证。

1. 登录 [Zoom App Marketplace](https://marketplace.zoom.us/)，创建或打开 **General App**。
2. 在应用的 **Features → Embed → Meeting SDK** 开启 Meeting SDK，保存应用的 **Client ID / Client Secret**。不要用 Server-to-Server OAuth 应用凭据代替。
3. 在 SDK 下载区域选择 **Linux、ARM64、7.0.5.3529**，下载后解压。下面用 `ZOOM_SDK_PATH` 指向包含 `h/`、`libmeetingsdk.so`、`qt_libs/`、`libglib2/`、`json/` 的目录，而不是压缩包或其上一层目录。
4. 使用**应用所属 Zoom 账号**创建并主持测试会议，记下数字会议号和会议密码。先复现同账号场景；跨账号入会未在本流程中验证。

如果下载页不提供这个旧版本，需要先取得官方对应安装包；不要用其他版本替换后直接视为同一套已验证配置。官方示例与 SDK 的许可分别适用，SDK 二进制不放入本仓库。

## 2. 填写本机配置

已有 `.env` 时直接编辑，不要覆盖；首次可执行：

```bash
cp -n .env.example .env
chmod 600 .env
```

用编辑器填写以下字段，不要把凭据提交到 Git：

```dotenv
ZOOM_CLIENT_ID=你的应用ClientID
ZOOM_CLIENT_SECRET=你的应用ClientSecret
ZOOM_MEETING_ID=不带空格的数字会议号
ZOOM_MEETING_PASSWORD=会议密码
ZOOM_SDK_PATH=/absolute/path/to/extracted-linux-arm64-sdk
```

这次同账号接收测试不需要手工填写 ZAK、OBF 或 JWT。启动脚本会读取前四个字段，生成一小时有效的 participant JWT；`ZOOM_SDK_PATH` 用于下面的构建步骤。若 shell 已导出同名变量，它们优先于 `.env`。

## 3. 构建已验证的接收程序

以下命令在 **Sparkie 仓库根目录**执行一次。它会下载固定版本的官方示例，应用仓库内的接收补丁，再复制你自行下载的 SDK。路径中可以包含空格。

```bash
mkdir -p .runtime
git clone https://github.com/zoom/meetingsdk-linux-raw-recording-sample.git .runtime/zoom-sanity-source
git -C .runtime/zoom-sanity-source checkout ed7e1fe12b0dcbf0a215079bb877077703da03fa
git -C .runtime/zoom-sanity-source apply ../../docs/zoom-sanity-assets/receive-only.patch

uv run --frozen python - <<'PY'
import os
from pathlib import Path
import shutil
from dotenv import load_dotenv

load_dotenv('.env')
sdk = Path(os.environ['ZOOM_SDK_PATH']).expanduser()
for name in ('h', 'libmeetingsdk.so', 'qt_libs', 'libglib2', 'json'):
    if not (sdk / name).exists():
        raise SystemExit(f'SDK 缺少 {name}，请核对 ZOOM_SDK_PATH 与下载版本')
build = Path('.runtime/zoom-sanity-7.0.5')
if build.exists():
    raise SystemExit('构建目录已存在；已有配置请直接使用下方 docker build，勿重复初始化')
shutil.copytree('.runtime/zoom-sanity-source/demo', build / 'demo')
demo = build / 'demo'
shutil.rmtree(demo / 'include', ignore_errors=True)
shutil.copytree(sdk / 'h', demo / 'include/h')
libs = demo / 'lib/zoom_meeting_sdk'
shutil.rmtree(libs, ignore_errors=True)
libs.mkdir(parents=True)
for name in ('libmeetingsdk.so', 'qt_libs', 'libglib2', 'json'):
    source = sdk / name
    if source.is_dir():
        shutil.copytree(source, libs / name)
    else:
        shutil.copy2(source, libs / name)
assets = Path('docs/zoom-sanity-assets')
for name in ('Dockerfile', '.dockerignore'):
    shutil.copy2(assets / name, build / name)
shutil.copy2(assets / 'config.txt', demo / 'config.txt')
print('构建目录已准备好')
PY

docker build --platform linux/arm64 -t sparkie-zoom-sanity:7.0.5 .runtime/zoom-sanity-7.0.5
```

首次构建需要联网下载 Ubuntu 和依赖。成功后会看到 `Successfully tagged sparkie-zoom-sanity:7.0.5` 或等价的 Docker 构建完成提示。此后无需重复 clone、应用补丁或复制 SDK。

补丁固定机器人名称为 **Sparkie**，关闭摄像头与音频发送，显式加入 VoIP、请求音频读取所需的本地录制权限，并打印 PCM 帧数和音量峰值。它不保存会议录音，未订阅视频，也不调用 STT/TTS/LLM。

## 4. 启动并授权

1. 主持人先用 Zoom 客户端或浏览器启动 `.env` 中配置的会议。
2. 在仓库根目录启动机器人并查看日志：

   ```bash
   uv run --frozen python scripts/zoom-sanity.py start
   uv run --frozen python scripts/zoom-sanity.py logs
   ```

3. 主持人在等待室点击 **Admit / 允许进入**，确认参与者列表出现 **Sparkie**。
4. 收到 Sparkie 请求本地录制的提示后，点击 **Allow Recording / 允许录制**。这是 SDK 读取原始会议音频需要的权限；Zoom 会显示录制提示，本探针只计算音量，不写入音频文件。
5. 人类参会者加入电脑音频，点击 **Unmute / 取消静音**，说几句话，再恢复静音。

只需一个主持端；如果同时用相同账号打开浏览器和桌面客户端，列表可能出现两个同名参会者。调试用浏览器端可改名 `Sanity Test Host`，真正的机器人始终叫 `Sparkie`。

## 5. 如何确认成功

依次确认三个独立条件：

| 条件 | 可观察证据 |
| --- | --- |
| 真实入会 | Zoom 参与者列表出现 Sparkie，日志出现 `In Meeting Now...` |
| 音频订阅成功 | `JOIN_VOIP result=0`，授权后持续出现 `ZOOM_AUDIO_FRAME_RECEIVED` |
| 收到实际声音 | 说话时 `ZOOM_AUDIO_LEVEL peak=...` 明显大于 0，静音后回落 |

本次真实记录：每帧 640 bytes；人类说话后峰值依次出现 **30449、32706、8859、6239**，随后回到 **0**。这是会议音频进入机器人的证据，不代表已经识别文字或理解发言。

`active_frames` 是当前调试计数，不作为发言时长或精准语音活动检测依据。验收看参与者、持续帧数与峰值变化，不要仅以 `SDKAuth=0` 或静音帧判断全部成功。

## 6. 停止、重启与常见问题

退出 `logs` 的 Ctrl+C 只结束日志查看。停止机器人：

```bash
uv run --frozen python scripts/zoom-sanity.py stop
```

更换会议、修改凭据或重建镜像后，先 stop 再 start。脚本遇到仍在运行的容器会提示 `Receiver already running`，不会自动替换它。

| 现象 | 检查方法 |
| --- | --- |
| `Prepared image missing` | 完成第 3 节构建，核对镜像名与 tag |
| `SDKAuth immediate result=0` 后始终没有认证成功回调 | 核对确实是 ARM64 **7.0.5.3529**。本机 7.1.5.4434 曾卡在 `AUTHRET_NONE`；相同凭据换 7.0.5 后成功。同步返回 0 只说明调用被接受 |
| 停在等待室 / 没看到机器人 | 主持人先启动正确会议，检查数字会议号和密码，再从等待室接纳 |
| 已入会但没有音频帧 | 检查 `JOIN_VOIP result=0` 和主持人的 Allow Recording 授权；仅自动加入音频设置不足以替代本次补丁的显式 `JoinVoip()` |
| 帧数增加但 `peak=0` | 确认说话的人真的在这场会议、已加入电脑音频、未静音，且选中了正确麦克风 |
| 修改 `.env` 后仍用旧配置 | stop 后 start；检查 shell 是否有覆盖 `.env` 的同名变量 |
| 只有离线模拟结果 | `scripts/primitive.sh`、`scripts/demo.sh` 是另一路模拟，不会启动 Zoom；使用本页的 `zoom-sanity.py` |

## 版本与交接边界

- 官方示例固定 commit：`ed7e1fe12b0dcbf0a215079bb877077703da03fa`，仓库为 [Zoom raw recording sample](https://github.com/zoom/meetingsdk-linux-raw-recording-sample)。配套文件在 [zoom-sanity-assets](zoom-sanity-assets)。
- 7.1.5 的认证回调问题另有 [Zoom 官方论坛记录](https://devforum.zoom.us/t/linux-meeting-sdk-sdkauth-succeeds-synchronously-but-onauthenticationreturn-never-fires-general-app-jwt-auth/146313)。本流程仅把实测成功的 7.0.5 作为基线，不声称验证了后续修复版。
- `.env`、`.runtime/` 和 SDK 不提交；启动时 JWT 配置写入权限为 600 的运行文件，挂载给容器。诊断日志留在本机，分享前去除凭据与无关会议信息。
- 已验证同账号的开发测试；跨账号授权、生产使用、长时间稳定性，以及完整语音闭环尚未验收。技术实测不替代 Zoom 的适用平台条款与授权要求。
