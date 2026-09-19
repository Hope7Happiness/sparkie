"""Shared configuration for the two receive-only Zoom probes (no SDK imports)."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time


def selected_platform(environ=None):
    environ = os.environ if environ is None else environ
    value = environ.get("ZOOM_PLATFORM") or "linux"
    if value not in {"linux", "macos"}:
        raise ValueError("ZOOM_PLATFORM must be linux or macos")
    return value


def sdk_path(target, environ=None):
    environ = os.environ if environ is None else environ
    # An explicit macOS path lets testers keep their Linux configuration intact.
    value = (environ.get("ZOOM_MACOS_SDK_PATH") if target == "macos" else None)
    return Path(value or environ.get("ZOOM_SDK_PATH") or ".runtime/missing-sdk").expanduser().resolve()


def sdk_present(target, path):
    if target == "macos":
        return (path / "ZoomSDK/ZoomSDK.framework/Headers/ZoomSDK.h").is_file()
    return (path / "h").is_dir() and (path / "libmeetingsdk.so").is_file()


def meeting_config(environ=None, now=None):
    environ = os.environ if environ is None else environ
    required = ["ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET", "ZOOM_MEETING_ID", "ZOOM_MEETING_PASSWORD"]
    if missing := [key for key in required if not environ.get(key)]:
        raise ValueError("Missing: " + ", ".join(missing))
    number = re.sub(r"[\s-]", "", environ["ZOOM_MEETING_ID"])
    if not re.fullmatch(r"[0-9]{9,11}", number):
        raise ValueError("ZOOM_MEETING_ID must be a 9–11 digit meeting number, not a URL")
    issued = int(time.time() if now is None else now) - 30
    payload = {"appKey": environ["ZOOM_CLIENT_ID"], "iat": issued,
               "exp": issued + 3600, "tokenExp": issued + 3600, "mn": number, "role": 0}
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=")
    body = b".".join(encode(json.dumps(x, separators=(",", ":")).encode())
                     for x in ({"alg": "HS256", "typ": "JWT"}, payload))
    token = (body + b"." + encode(hmac.new(environ["ZOOM_CLIENT_SECRET"].encode(), body, hashlib.sha256).digest())).decode()
    return {"meeting_number": number, "token": token,
            "meeting_password": environ["ZOOM_MEETING_PASSWORD"], "display_name": "Sparkie"}


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        os.fchmod(out.fileno(), 0o600)
        out.write(text)
