# Zoom SDK 配置状态与操作

2026-09-19 最新状态：Sparkie 已创建为 User-managed General App，Development 模式下 Meeting SDK 已开启。本地开发凭据已填写；原生 macOS SDK 实测返回 `SDK_INIT=0`、`SDK_AUTH_REQUEST=0`、`SDK_AUTH_RESULT=0`，**Zoom 服务端认证成功**。会议号仍为空，programmatic join 选项在最后一次检查时未开启。

用户已将 macOS SDK 7.1.5.84750 解压至 `/Users/yifankang/zoom-sdk-macos-7.1.5.84750`，包含 arm64 与 x86_64。本地认证程序直接链接这份 SDK，使用 `.runtime/SparkieAuthCheck.app`，不复制 SDK 到 Git。SDK 运行中有供应商库重复 Objective-C 类的警告，未阻止认证；不能据此推断媒体功能也已通过。现有 Docker 命令执行报 bad CPU type in executable，本轮使用原生 macOS 环境。

重新编译并验证真实认证：

```sh
python3 scripts/zoom_macos_auth.py --sdk /Users/yifankang/zoom-sdk-macos-7.1.5.84750
```

此程序只认证，不加入会议、采集音频或录制。认证等待最多 45 秒，进程总超时 60 秒。SDK 保存在外部目录，因此不能删除或移动该目录后继续运行已有程序；若移动，使用新的 `--sdk` 路径重新构建。

验证记录：修正启动调度和回调后的 SDK 清理后，最新运行的三项结果均为 0，进程退出码为 0。诊断输出保存在被 Git 忽略的 `.runtime/zoom-auth-check.log`。

## 账号权限要求（当前已解除阻塞）

由当前 Zoom 账号管理员在 User Management → Roles → Role Settings → Advanced features 开放 **Zoom for developers 的 View/Edit**，并确认 **SDK 的 View/Edit**。或切换到拥有这些权限的个人账号。这里的角色权限是应用创建权限，不能通过修改本地代码解决。[General App 前提](https://developers.zoom.us/docs/build-flow/create-oauth-apps/#prerequisites) · [SDK 前提](https://developers.zoom.us/docs/meeting-sdk/get-credentials/)

权限恢复后创建 General App → 命名 Sparkie → Features → Embed → Meeting SDK。下载目标平台 SDK，开发凭据写入 `config/zoom.local.json`；不要填生产凭据或把 Secret 发到聊天、提交 Git。

第一轮会议应由应用所属账号主持。若用另一个个人账号创建应用，需要用该个人账号主持测试会议，不能默认加入当前组织的会议。[SDK 授权](https://developers.zoom.us/docs/meeting-sdk/auth/)

## 本地准备

工具只使用 Python 标准库，无需安装依赖。

```sh
python3 scripts/zoom_config.py init
# 在编辑器填写 config/zoom.local.json
python3 scripts/zoom_config.py check
python3 scripts/zoom_config.py token
```

`init` 不覆盖已有配置。`check` 只验证字段；`token` 使用 HS256 签发原生 Meeting SDK JWT，写入 `.runtime/zoom-sdk.jwt`。私密文件权限为 0600，已添加 Git 忽略规则。JWT 并不是 OAuth access token，不能拿它调用 Zoom REST API。

入会测试已实现：加 `--join` 从本地私密配置读取会议号、密码和显示名，关闭音频与视频后发送 SDK 入会请求。当前是最多 3 分钟的连接测试，不是常驻 agent。

```sh
python3 scripts/zoom_macos_auth.py --sdk /Users/yifankang/zoom-sdk-macos-7.1.5.84750 --join
```

2026-09-19 MIT 会议实测：认证成功，`SDK_JOIN_REQUEST=0`（请求被 SDK 接受），随后 `SDK_MEETING_STATUS=6 ERROR=63`，即 `ZoomSDKMeetingError_UnableToJoinExternalMeeting`。SDK 头文件说明外部 Zoom 账号主持的会议需要应用发布/审核。未成功进入会议，未采集音视频，也未验证链接中的密码参数是否通过。会议凭据只保存在被 Git 忽略的本地配置中。

下一步用创建 Sparkie 的同一账号主持测试会议；若必须加入 MIT 会议，需要外部会议应用审核及 OAuth/OBF 授权。不要把认证成功或 join 请求同步返回 0 当作已经入会。

macOS 若出现钥匙串访问提示，需要用户在系统中完成授权，不能在日志/聊天里填写 Mac 密码。脚本复用未改动的构建，减少重复构建造成的应用身份变化。

后续同账号会议实测成功：状态依次包含 InWaitingRoom（10）、InMeeting（3），用户也确认看到入会成功。之后收到 Ended（7）和 EndByHost（2），表示主持人结束会议。已验证本地 SDK、开发凭据及该会议链接密码参数可用于本次入会。

仍未完成：双向音频收发、语音识别、唤醒和语音回复。本次测试关闭摄像头和音频，不把入会成功算作音频验收。

完整音频接入与队友接口见 [参会方案](zoom-agent-integration.md)。
