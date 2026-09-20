#!/usr/bin/env python3
"""Build and run an auth-only probe against the locally downloaded Zoom SDK."""
import argparse
import hashlib
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--sdk", type=Path, required=True, help="Extracted macOS SDK directory")
parser.add_argument("--join", action="store_true", help="Join the configured meeting with camera and audio off (3 minute test)")
args = parser.parse_args()
sdk = args.sdk.expanduser().resolve()
frameworks = sdk / "ZoomSDK"
if not (frameworks / "ZoomSDK.framework/ZoomSDK").is_file():
    parser.error("Missing ZoomSDK/ZoomSDK.framework/ZoomSDK")
subprocess.run([sys.executable, str(ROOT / "scripts/zoom_config.py"), "token"], check=True)
if args.join:
    subprocess.run([sys.executable, str(ROOT / "scripts/zoom_config.py"), "check"], check=True)
bundle = ROOT / ".runtime/SparkieAuthCheck.app/Contents"
(bundle / "MacOS").mkdir(parents=True, exist_ok=True)
link = bundle / "Frameworks"
if link.is_symlink():
    if link.resolve() != frameworks:
        link.unlink()
        link.symlink_to(frameworks, target_is_directory=True)
elif not link.exists():
    link.symlink_to(frameworks, target_is_directory=True)
else:
    parser.error("Unexpected existing Frameworks directory; will not overwrite")
with (bundle / "Info.plist").open("wb") as stream:
    plistlib.dump({"CFBundleIdentifier": "local.sparkie.authcheck",
                  "CFBundleExecutable": "SparkieAuthCheck",
                  "CFBundleName": "Sparkie Auth Check", "CFBundlePackageType": "APPL",
                  "CFBundleVersion": "1", "LSUIElement": True}, stream)
binary = bundle / "MacOS/SparkieAuthCheck"
source = ROOT / "native/zoom_auth_check.m"
build_key = hashlib.sha256(source.read_bytes() + str(frameworks).encode()).hexdigest()
stamp = bundle / "build-key"
if not binary.exists() or not stamp.exists() or stamp.read_text() != build_key:
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-framework", "Cocoa",
                "-F" + str(frameworks), "-framework", "ZoomSDK",
                "-Wl,-rpath,@executable_path/../Frameworks",
                str(source), "-o", str(binary)], check=True)
    stamp.write_text(build_key)
print("Native SDK test built; " + ("joining configured meeting with audio/video off." if args.join else "authentication only."), flush=True)
command = [str(binary), str(ROOT / ".runtime/zoom-sdk.jwt")]
if args.join:
    command.append(str(ROOT / "config/zoom.local.json"))
try:
    result = subprocess.run(command, timeout=180 if args.join else 60)
except subprocess.TimeoutExpired:
    sys.exit("SDK test timed out. Check meeting status log and macOS Keychain prompts.")
sys.exit(result.returncode)
