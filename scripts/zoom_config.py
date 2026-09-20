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
            print("Created config/zoom.local.json (readable and writable only by the current user).")
        except FileExistsError:
            print("Local configuration already exists; it was not overwritten.")
        return 0
    try:
        config = json.loads(CONFIG.read_text())
    except FileNotFoundError:
        print("Run python3 scripts/zoom_config.py init first.", file=sys.stderr)
        return 1
    except (ValueError, OSError):
        print("Cannot read local configuration. Check JSON syntax and file permissions.", file=sys.stderr)
        return 1
    if not isinstance(config, dict):
        print("Configuration must be a JSON object.", file=sys.stderr)
        return 1
    required = ["client_id", "client_secret"]
    if args.command == "check":
        required += ["meeting_number", "display_name"]
    missing = [key for key in required
               if not isinstance(config.get(key), str) or not config[key].strip()]
    if missing:
        print("Missing configuration fields: " + ", ".join(missing), file=sys.stderr)
        return 1
    if args.command == "check":
        number = config["meeting_number"]
        if not number.isascii() or not number.isdigit() or len(number) not in (10, 11):
            print("meeting_number must be a string of 10–11 digits, without spaces or a URL.", file=sys.stderr)
            return 1
        if not isinstance(config.get("meeting_password"), str):
            print("meeting_password must be a string; use an empty string if no password is required.", file=sys.stderr)
            return 1
        print("Local fields are valid. Credentials and meeting access have not been verified with Zoom.")
        return 0
    TOKEN.parent.mkdir(mode=0o700, exist_ok=True)
    private_write(TOKEN, make_jwt(config["client_id"], config["client_secret"], time.time()) + "\n")
    print("SDK JWT saved to .runtime/zoom-sdk.jwt; valid for about two hours. Token not printed.")
    print("Local signing only. The native SDK authentication callback must confirm acceptance by Zoom.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
