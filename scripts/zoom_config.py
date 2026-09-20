#!/usr/bin/env python3
"""Local native Meeting SDK configuration and JWT preparation; does not join Zoom."""

import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/zoom.local.json"
TOKEN = ROOT / ".runtime/zoom-sdk.jwt"


def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def make_jwt(client_id, client_secret, now):
    issued = int(now) - 30
    claims = {
        "appKey": client_id,
        "iat": issued,
        "exp": issued + 7200,
        "tokenExp": issued + 7200,
    }
    segments = [encode(json.dumps(obj, separators=(",", ":")).encode())
                for obj in ({"alg": "HS256", "typ": "JWT"}, claims)]
    body = ".".join(segments)
    signature = hmac.new(client_secret.encode(), body.encode(), hashlib.sha256).digest()
    return body + "." + encode(signature)


def private_write(path, text, exclusive=False):
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
    flags |= os.O_EXCL if exclusive else os.O_TRUNC
    fd = os.open(str(path), flags, 0o600)
    with os.fdopen(fd, "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "check", "token"))
    args = parser.parse_args()
    if args.command == "init":
        try:
            private_write(CONFIG, (ROOT / "config/zoom.example.json").read_text(), True)
            print("已创建 config/zoom.local.json（仅当前用户可读写）。")
        except FileExistsError:
            print("本地配置已存在，未覆盖。")
        return 0
    try:
        config = json.loads(CONFIG.read_text())
    except FileNotFoundError:
        print("请先运行 python3 scripts/zoom_config.py init。", file=sys.stderr)
        return 1
    except (ValueError, OSError):
        print("无法读取本地配置；请检查 JSON 格式和文件权限。", file=sys.stderr)
        return 1
    if not isinstance(config, dict):
        print("配置必须为 JSON 对象。", file=sys.stderr)
        return 1
    required = ["client_id", "client_secret"]
    if args.command == "check":
        required += ["meeting_number", "display_name"]
    missing = [key for key in required
               if not isinstance(config.get(key), str) or not config[key].strip()]
    if missing:
        print("缺少配置项：" + ", ".join(missing), file=sys.stderr)
        return 1
    if args.command == "check":
        number = config["meeting_number"]
        if not number.isascii() or not number.isdigit() or len(number) not in (10, 11):
            print("meeting_number 需为 10–11 位数字字符串，不含空格或链接。", file=sys.stderr)
            return 1
        if not isinstance(config.get("meeting_password"), str):
            print("meeting_password 需为字符串；无密码时填写空字符串。", file=sys.stderr)
            return 1
        print("本地字段检查通过；尚未向 Zoom 验证凭据，也未验证入会能力。")
        return 0
    TOKEN.parent.mkdir(mode=0o700, exist_ok=True)
    private_write(TOKEN, make_jwt(config["client_id"], config["client_secret"], time.time()) + "\n")
    print("SDK JWT 已写入 .runtime/zoom-sdk.jwt，约 2 小时有效（未输出 token）。")
    print("这只完成本地签名；需原生 SDK 的认证成功回调验证 Zoom 是否接受。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
