#!/usr/bin/env python3
"""Connect to a Wi-Fi network and host a local FPS dashboard.

This script attempts to connect to the SSID `MV-GUEST` using NetworkManager
(`nmcli`), discovers the machine's LAN IP address, and starts a Flask web
server bound to that IP.

The web page shows a live camera stream and current FPS.
"""

from __future__ import annotations

import argparse
import platform
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Optional

from flask import Flask, Response, jsonify, render_template_string

try:
    import cv2
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit(
        "Missing dependency: opencv-python. Install with: pip install opencv-python"
    ) from exc


HTML_PAGE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>FPS Monitor</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; padding: 2rem; background: #0f172a; color: #e2e8f0; }
    .card { max-width: 900px; margin: 0 auto; background: #111827; border-radius: 16px; padding: 1.2rem; box-shadow: 0 10px 30px rgba(0,0,0,.25); }
    h1 { margin-top: 0; }
    .meta { margin-bottom: 1rem; color: #94a3b8; }
    .fps { font-size: 1.5rem; font-weight: bold; color: #22d3ee; }
    img { width: 100%; border-radius: 10px; border: 1px solid #334155; }
    code { background: #1f2937; padding: .2rem .4rem; border-radius: 6px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Live FPS Dashboard</h1>
    <div class="meta">Server: <code>{{ host }}:{{ port }}</code></div>
    <div class="fps">FPS: <span id="fps">--</span></div>
    <img src="/video_feed" alt="Camera stream">
  </div>

  <script>
    async function updateFps() {
      try {
        const res = await fetch('/fps');
        const data = await res.json();
        document.getElementById('fps').textContent = data.fps.toFixed(2);
      } catch (_) {
        document.getElementById('fps').textContent = 'N/A';
      }
    }
    setInterval(updateFps, 500);
    updateFps();
  </script>
</body>
</html>
"""


@dataclass
class CameraState:
    fps: float = 0.0
    frame_jpeg: bytes = b""
    last_error: Optional[str] = None


def connect_wifi(ssid: str, password: str | None = None) -> None:
    """Connect to Wi-Fi via nmcli on Linux."""
    if platform.system() != "Linux":
        print("Skipping Wi-Fi connect: automatic connection is implemented for Linux + nmcli.")
        return

    # Check nmcli availability first.
    check = subprocess.run(["nmcli", "-v"], capture_output=True, text=True)
    if check.returncode != 0:
        raise RuntimeError(
            "nmcli not found. Install NetworkManager or connect manually before running this script."
        )

    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd.extend(["password", password])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to connect to Wi-Fi '{ssid}'.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    print(result.stdout.strip())


def get_local_ip() -> str:
    """Best-effort local IP discovery."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]


def frame_worker(camera_index: int, state: CameraState, stop_event: threading.Event) -> None:
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        state.last_error = f"Could not open camera index {camera_index}."
        return

    last_time = time.perf_counter()
    frame_count = 0

    while not stop_event.is_set():
        ok, frame = cap.read()
        if not ok:
            state.last_error = "Camera frame read failed."
            time.sleep(0.05)
            continue

        frame_count += 1
        now = time.perf_counter()
        elapsed = now - last_time
        if elapsed >= 1.0:
            state.fps = frame_count / elapsed
            frame_count = 0
            last_time = now

        overlay = frame.copy()
        cv2.putText(
            overlay,
            f"FPS: {state.fps:.2f}",
            (10, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

        ok_enc, buffer = cv2.imencode(".jpg", overlay)
        if ok_enc:
            state.frame_jpeg = buffer.tobytes()

    cap.release()


def create_app(state: CameraState, host: str, port: int) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index() -> str:
        return render_template_string(HTML_PAGE, host=host, port=port)

    @app.get("/fps")
    def fps() -> Response:
        return jsonify({"fps": state.fps, "error": state.last_error})

    @app.get("/video_feed")
    def video_feed() -> Response:
        def generate():
            while True:
                if state.frame_jpeg:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + state.frame_jpeg + b"\r\n"
                    )
                else:
                    time.sleep(0.05)

        return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Connect to Wi-Fi and host an FPS web server.")
    parser.add_argument("--ssid", default="MV-GUEST", help="Wi-Fi SSID (default: MV-GUEST)")
    parser.add_argument("--password", default=None, help="Wi-Fi password if required")
    parser.add_argument("--port", type=int, default=5000, help="Port for the web server")
    parser.add_argument("--camera-index", type=int, default=0, help="OpenCV camera index")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        connect_wifi(args.ssid, args.password)
    except Exception as exc:
        print(f"Warning: Wi-Fi auto-connect failed: {exc}")
        print("Continuing anyway. If needed, connect manually before opening the page.")

    host = get_local_ip()
    print(f"Local IP detected: {host}")
    print(f"Open this URL on the same network: http://{host}:{args.port}")

    state = CameraState()
    stop_event = threading.Event()
    worker = threading.Thread(
        target=frame_worker,
        args=(args.camera_index, state, stop_event),
        daemon=True,
    )
    worker.start()

    app = create_app(state, host, args.port)
    try:
        app.run(host="0.0.0.0", port=args.port, threaded=True)
    finally:
        stop_event.set()
        worker.join(timeout=2)


if __name__ == "__main__":
    main()
