#!/usr/bin/env python3
"""HERMES Bridge — Local REST server for Samsung DeX via scrcpy + ADB."""

import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from urllib.parse import urlparse

PORT = 8314
HERMES_DIR = pathlib.Path(__file__).parent.resolve()
CONFIG_DIR = pathlib.Path.home() / ".hermes"
CONFIG_FILE = CONFIG_DIR / "config.json"

# --- Tool Discovery ---

def find_executable(name):
    """Find an executable in PATH or common install locations."""
    found = shutil.which(name)
    if found:
        return found
    common_paths = [
        pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools",
        pathlib.Path("C:/scrcpy"),
        pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
    ]
    for p in common_paths:
        candidate = p / f"{name}.exe"
        if candidate.exists():
            return str(candidate)
    return None

SCRCPY_PATH = find_executable("scrcpy")
ADB_PATH = find_executable("adb")

# --- Config ---

DEFAULT_CONFIG = {
    "lastUsed": {
        "resolution": "1920x1080",
        "dpi": 240,
        "fps": 60,
        "bitrate": "16M",
        "screenOff": True,
        "mode": "usb"
    },
    "presets": [
        {"name": "USB High Quality", "resolution": "2560x1440", "dpi": 240, "fps": 60, "bitrate": "20M", "screenOff": True},
        {"name": "Wireless Chill", "resolution": "1920x1080", "dpi": 240, "fps": 60, "bitrate": "8M", "screenOff": True}
    ]
}

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()

def save_config(config):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

# --- ADB Helpers ---

def run_adb(*args, timeout=10):
    """Run an ADB command, return (success, stdout)."""
    if not ADB_PATH:
        return False, "ADB not found"
    try:
        result = subprocess.run(
            [ADB_PATH] + list(args),
            capture_output=True, text=True, timeout=timeout
        )
        return result.returncode == 0, result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "ADB command timed out"
    except Exception as e:
        return False, str(e)

def get_device_status():
    """Get connected device info."""
    ok, output = run_adb("devices")
    if not ok:
        return {"connected": False, "error": output}

    lines = [l for l in output.splitlines()[1:] if l.strip() and "device" in l]
    if not lines:
        return {"connected": False}

    serial = lines[0].split("\t")[0]
    is_wireless = ":" in serial

    _, model = run_adb("shell", "getprop", "ro.product.model")
    _, android_ver = run_adb("shell", "getprop", "ro.build.version.release")

    _, battery_out = run_adb("shell", "dumpsys", "battery")
    battery_pct = None
    for line in battery_out.splitlines():
        if "level:" in line:
            try:
                battery_pct = int(line.split(":")[1].strip())
            except ValueError:
                pass
            break

    ip_addr = None
    if is_wireless:
        ip_addr = serial.split(":")[0]
    else:
        _, route_out = run_adb("shell", "ip", "route")
        for line in route_out.splitlines():
            if "wlan0" in line and "src" in line:
                parts = line.split("src")
                if len(parts) > 1:
                    ip_addr = parts[1].strip().split()[0]
                break

    return {
        "connected": True,
        "serial": serial,
        "model": model or "Unknown",
        "androidVersion": android_ver or "Unknown",
        "battery": battery_pct,
        "connectionType": "wireless" if is_wireless else "usb",
        "ip": ip_addr
    }

# --- scrcpy Session ---

scrcpy_process = None
scrcpy_lock = threading.Lock()

def launch_scrcpy(params):
    """Launch scrcpy with DeX mode."""
    global scrcpy_process
    if not SCRCPY_PATH:
        return False, "scrcpy not found"

    with scrcpy_lock:
        if scrcpy_process and scrcpy_process.poll() is None:
            return False, "Session already active"

    run_adb("shell", "settings", "put", "global", "force_desktop_mode_on_external_displays", "1")
    run_adb("shell", "settings", "put", "global", "enable_freeform_support", "1")

    resolution = params.get("resolution", "1920x1080")
    dpi = params.get("dpi", 240)
    fps = params.get("fps", 60)
    bitrate = params.get("bitrate", "16M")
    screen_off = params.get("screenOff", True)

    cmd = [
        SCRCPY_PATH,
        f"--new-display={resolution}/{dpi}",
        f"--video-bit-rate={bitrate}",
        f"--max-fps={fps}",
        "--stay-awake",
        "--power-off-on-close",
    ]
    if screen_off:
        cmd.append("--turn-screen-off")

    try:
        with scrcpy_lock:
            scrcpy_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            )
        config = load_config()
        config["lastUsed"] = params
        save_config(config)
        return True, f"DeX launched (PID {scrcpy_process.pid})"
    except Exception as e:
        return False, str(e)

def kill_scrcpy():
    """Kill active scrcpy session."""
    global scrcpy_process
    with scrcpy_lock:
        if scrcpy_process and scrcpy_process.poll() is None:
            scrcpy_process.terminate()
            try:
                scrcpy_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                scrcpy_process.kill()
            scrcpy_process = None
            return True, "Session terminated"
        return False, "No active session"

def is_scrcpy_running():
    with scrcpy_lock:
        return scrcpy_process is not None and scrcpy_process.poll() is None

# --- Auto-Shutdown Timer ---

last_activity = time.time()
IDLE_TIMEOUT = 1800  # 30 minutes

def activity():
    global last_activity
    last_activity = time.time()

def idle_watchdog():
    while True:
        time.sleep(60)
        if time.time() - last_activity > IDLE_TIMEOUT and not is_scrcpy_running():
            print("[HERMES] Idle timeout — shutting down.")
            os._exit(0)

# --- HTTP Handler ---

class HermesHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "http://localhost:8314")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, filepath, content_type):
        with open(filepath, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(content))
        self.end_headers()
        self.wfile.write(content)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://localhost:8314")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        activity()
        path = urlparse(self.path).path

        if path == "/" or path == "/index.html":
            index = HERMES_DIR / "index.html"
            if index.exists():
                self.send_file(index, "text/html")
            else:
                self.send_json({"error": "index.html not found"}, 404)

        elif path == "/api/status":
            status = get_device_status()
            status["scrcpyRunning"] = is_scrcpy_running()
            status["scrcpyAvailable"] = SCRCPY_PATH is not None
            status["adbAvailable"] = ADB_PATH is not None
            self.send_json(status)

        elif path == "/api/settings":
            self.send_json(load_config())

        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        activity()
        path = urlparse(self.path).path
        content_len = int(self.headers.get("Content-Length", 0))
        body = {}
        if content_len > 0:
            raw = self.rfile.read(content_len)
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                self.send_json({"error": "Invalid JSON"}, 400)
                return

        if path == "/api/launch":
            ok, msg = launch_scrcpy(body)
            self.send_json({"success": ok, "message": msg}, 200 if ok else 500)

        elif path == "/api/disconnect":
            ok, msg = kill_scrcpy()
            self.send_json({"success": ok, "message": msg})

        elif path == "/api/adb/restart":
            run_adb("kill-server")
            time.sleep(1)
            ok, msg = run_adb("start-server")
            self.send_json({"success": ok, "message": msg})

        elif path == "/api/adb/wireless":
            ip = body.get("ip")
            if not ip:
                self.send_json({"error": "IP required"}, 400)
                return
            run_adb("tcpip", "5555")
            time.sleep(2)
            ok, msg = run_adb("connect", f"{ip}:5555")
            self.send_json({"success": ok, "message": msg})

        else:
            self.send_json({"error": "Not found"}, 404)

    def do_PUT(self):
        activity()
        path = urlparse(self.path).path
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len == 0:
            self.send_json({"error": "No body"}, 400)
            return
        raw = self.rfile.read(content_len)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON"}, 400)
            return

        if path == "/api/settings":
            save_config(body)
            self.send_json({"success": True})
        else:
            self.send_json({"error": "Not found"}, 404)

# --- Main ---

def main():
    if not SCRCPY_PATH:
        print("[HERMES] WARNING: scrcpy not found. Install via: winget install Genymobile.scrcpy")
    if not ADB_PATH:
        print("[HERMES] WARNING: ADB not found. Install via: winget install Google.PlatformTools")

    watchdog = threading.Thread(target=idle_watchdog, daemon=True)
    watchdog.start()

    server = http.server.HTTPServer(("127.0.0.1", PORT), HermesHandler)
    print(f"[HERMES] Bridge running on http://localhost:{PORT}")

    webbrowser.open(f"http://localhost:{PORT}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[HERMES] Shutting down...")
        kill_scrcpy()
        server.shutdown()

if __name__ == "__main__":
    main()
