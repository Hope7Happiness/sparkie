"""Build and manage the native macOS receive-only probe. SDK stays outside Git."""
import json
import hashlib
import os
from pathlib import Path
import platform
import plistlib
import shutil
import signal
import subprocess
import time

from .zoom_config import meeting_config, private_write, sdk_path, sdk_present


def paths(root):
    runtime = root / ".runtime/zoom-macos"
    app = runtime / "SparkieZoom.app"
    return runtime, app, app / "Contents/MacOS/SparkieZoom"


def require_macos():
    if platform.system() != "Darwin":
        raise ValueError("macos requires a logged-in macOS desktop with Xcode; use --platform linux here")


def running_pid(root):
    runtime, _, binary = paths(root)
    try:
        pid = int((runtime / "receiver.pid").read_text())
    except (OSError, ValueError):
        return None
    if pid <= 1:
        return None
    result = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    # Never signal an unrelated process after a stale PID file / PID reuse.
    return pid if result.returncode == 0 and result.stdout.strip() == str(binary) else None


def build(root):
    require_macos()
    if running_pid(root):
        raise ValueError("Stop the macOS receiver before rebuilding")
    sdk = sdk_path("macos")
    if not sdk_present("macos", sdk):
        raise ValueError("ZOOM_MACOS_SDK_PATH (or ZOOM_SDK_PATH) must contain ZoomSDK/ZoomSDK.framework")
    runtime, app, binary = paths(root)
    # Build in staging; a compiler/signing failure leaves the previous app intact.
    # iCloud Documents can reattach FinderInfo during signing. Keep binaries local.
    identity = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    storage = Path.home() / "Library/Application Support/Sparkie/ZoomReceivers" / identity
    installed = storage / "SparkieZoom.app"
    staging = storage / "staging/SparkieZoom.app"
    if staging.exists():
        shutil.rmtree(staging)
    contents = staging / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    frameworks = contents / "Frameworks"
    subprocess.run(["ditto", str(sdk / "ZoomSDK"), str(frameworks)], check=True)
    info = {"CFBundleExecutable": "SparkieZoom", "CFBundleIdentifier": "dev.sparkie.zoom-receiver",
            "CFBundleName": "Sparkie Zoom Receiver", "CFBundlePackageType": "APPL",
            "CFBundleVersion": "1", "CFBundleShortVersionString": "0.1.0",
            "NSPrincipalClass": "NSApplication", "LSMinimumSystemVersion": "12.0",
            "NSMicrophoneUsageDescription": "Connect to meeting audio. This probe joins muted.",
            "NSCameraUsageDescription": "This receive-only probe keeps video off."}
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    # Bundle localized permission descriptions; no user-facing web UI changes.
    for locale, text in {
        "en": '"NSMicrophoneUsageDescription" = "Connect to meeting audio. This probe joins muted.";\n"NSCameraUsageDescription" = "This receive-only probe keeps video off.";\n',
        "zh-Hans": '"NSMicrophoneUsageDescription" = "连接会议音频；此探针以静音状态加入。";\n"NSCameraUsageDescription" = "此接收探针始终关闭视频。";\n',
    }.items():
        resource = contents / "Resources" / f"{locale}.lproj"
        resource.mkdir(parents=True)
        (resource / "InfoPlist.strings").write_text(text)
    subprocess.run(["xcrun", "clang", "-fobjc-arc", "-fblocks", "-Werror=implicit-function-declaration",
                    "-Werror=objc-method-access", "-Werror=protocol", "-mmacosx-version-min=12.0", "-framework", "Cocoa",
                    "-framework", "ZoomSDK", "-F", str(frameworks),
                    "-Wl,-rpath,@executable_path/../Frameworks", str(root / "native/zoom-macos/main.m"),
                    "-o", str(contents / "MacOS/SparkieZoom")], check=True)
    # Finder/iCloud metadata on a Documents checkout can invalidate code signing.
    # Strip only prohibited resource metadata from the copy, preserving quarantine.
    for attribute in ("com.apple.FinderInfo", "com.apple.ResourceFork"):
        subprocess.run(["xattr", "-dr", attribute, str(staging)], check=True)
    # Sign only the copied runtime, never modify the user's SDK download.
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(staging)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(staging)], check=True)
    if installed.exists():
        shutil.rmtree(installed)
    staging.rename(installed)
    runtime.mkdir(parents=True, exist_ok=True)
    if app.is_symlink():
        app.unlink()
    elif app.exists():
        shutil.rmtree(app)
    app.symlink_to(installed, target_is_directory=True)
    print("macOS receiver built. Run check to verify local SDK loading; start joins a real meeting.")


def check(root):
    if running_pid(root):
        raise ValueError("Stop the macOS receiver before running the SDK load check")
    _, _, binary = paths(root)
    if not binary.is_file():
        raise ValueError("Build the macOS receiver first: zoom-sanity.py build --platform macos")
    try:
        subprocess.run([str(binary), "--check"], check=True, timeout=30)
    except subprocess.TimeoutExpired:
        raise ValueError("SDK initialization timed out. Check macOS Keychain prompts; rebuilding an ad-hoc signed app may require approval again. See docs/zoom-macos.md.") from None


def child_env():
    # Never forward project API credentials or the signing secret to the SDK process.
    return {key: value for key, value in os.environ.items()
            if key in {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL", "USER", "LOGNAME", "__CF_USER_TEXT_ENCODING"}}


def start(root):
    runtime, _, binary = paths(root)
    if running_pid(root):
        print("macOS receiver already running. Use logs or stop.")
        return
    if not binary.is_file():
        raise ValueError("Build the macOS receiver first: zoom-sanity.py build --platform macos")
    config = runtime / "config.json"
    private_write(config, json.dumps(meeting_config()))
    logfile = runtime / "receiver.log"
    private_write(logfile, "")
    env = child_env()
    env["SPARKIE_ZOOM_CONFIG"] = str(config)
    with logfile.open("a") as log:
        process = subprocess.Popen([str(binary)], env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    private_write(runtime / "receiver.pid", str(process.pid))
    try:
        status = process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        print("macOS receiver launched; join is not yet verified. Use logs; host must admit Sparkie and grant recording permission.")
    else:
        config.unlink(missing_ok=True)
        (runtime / "receiver.pid").unlink(missing_ok=True)
        raise ValueError(f"macOS receiver exited ({status}); inspect .runtime/zoom-macos/receiver.log")


def stop(root):
    runtime, _, _ = paths(root)
    pid = running_pid(root)
    if pid:
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 10
        while running_pid(root) == pid and time.monotonic() < deadline:
            time.sleep(.2)
        if running_pid(root) == pid:
            raise ValueError("Receiver did not stop; inspect it before retrying. No forced kill was sent.")
    (runtime / "receiver.pid").unlink(missing_ok=True)
    (runtime / "config.json").unlink(missing_ok=True)
    print("macOS receiver stopped.")


def run(command, root):
    require_macos()
    runtime, _, _ = paths(root)
    runtime.mkdir(parents=True, exist_ok=True)
    if command == "logs":
        logfile = runtime / "receiver.log"
        if not logfile.exists():
            raise ValueError("No macOS receiver log yet. Run start first.")
        subprocess.run(["tail", "-n", "50", "-F", str(logfile)], check=True)
        return
    # Serialize start/stop/build so two terminals cannot replace a live configuration.
    import fcntl
    with (runtime / "control.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        {"build": build, "check": check, "start": start, "stop": stop}[command](root)
