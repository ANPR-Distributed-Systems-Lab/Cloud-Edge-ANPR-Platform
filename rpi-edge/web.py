"""HTTP server: the control page, a JSON API and the MJPEG preview.

No authentication: it is meant for a private network (the phone hotspot in the car).
"""
import json
import os
import socketserver
import threading
from http import server

import settings as cfg
from camera_service import CameraService
from jsonlog import log
from storage import Storage

UI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui", "index.html")


class App:
    def __init__(self, store: cfg.SettingsStore, storage: Storage, camera: CameraService) -> None:
        self.store = store
        self.storage = storage
        self.camera = camera
        self.lock = threading.Lock()  # guards the preview client counter


def make_server(app: App, port: int) -> server.HTTPServer:
    class Handler(server.BaseHTTPRequestHandler):
        # --- helpers -----------------------------------------------------------------------------------------

        def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict, code: int = 200) -> None:
            self._send(code, json.dumps(payload, default=str).encode(), "application/json")

        def _error(self, message: str, code: int = 400) -> None:
            self._json({"ok": False, "error": message}, code)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                data = json.loads(self.rfile.read(length))
            except ValueError:
                return {}
            return data if isinstance(data, dict) else {}

        def _state(self) -> dict:
            return {
                "ok": True,
                "settings": app.store.get(),
                "status": app.camera.status(),
                "resolutions": list(cfg.RESOLUTIONS),
                "max_fps": cfg.MAX_SENSOR_FPS,
            }

        # --- routes ------------------------------------------------------------------------------------------

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            try:
                if path == "/":
                    with open(UI_PATH, "rb") as f:
                        self._send(200, f.read(), "text/html; charset=utf-8")
                elif path == "/api/state":
                    self._json(self._state())
                elif path == "/preview.mjpg":
                    self._preview()
                elif path == "/focus.jpg":
                    app.camera.focus_requested()
                    frame = app.camera.focus.frame
                    if frame is None:
                        self._send(204, b"", "image/jpeg")
                    else:
                        sharp = app.camera.focus_info.get("sharpness", 0.0)
                        self._send(200, frame, "image/jpeg", {"X-Sharpness": f"{sharp:.1f}"})
                elif path == "/snapshot.jpg":
                    snap = app.camera.last_snapshot
                    if snap is None:
                        self._send(404, b"no snapshot yet", "text/plain")
                    else:
                        extra = {"Content-Disposition": f'inline; filename="{snap["info"]["name"]}"'}
                        self._send(200, snap["jpeg"], "image/jpeg", extra)
                else:
                    self._send(404, b"not found", "text/plain")
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            body = self._body()
            try:
                if path == "/api/settings":
                    app.camera.update_settings(body)
                    self._json(self._state())
                elif path == "/api/white_balance/lock":
                    app.camera.lock_white_balance()
                    self._json(self._state())
                elif path == "/api/snapshot":
                    info = app.camera.snapshot()
                    self._json({"ok": True, "snapshot": info})
                elif path == "/api/record":
                    if body.get("action") == "start":
                        app.camera.start_recording("user")
                    elif body.get("action") == "stop":
                        app.camera.stop_recording("user")
                    else:
                        return self._error("action must be start or stop")
                    self._json(self._state())
                elif path == "/api/storage":
                    if body.get("action") == "mount":
                        app.storage.allow_remount()
                        app.storage.mount()
                    elif body.get("action") == "eject":
                        if app.camera.recording_status() is not None:
                            return self._error("Stop recording before ejecting the USB stick")
                        app.storage.eject()
                    else:
                        return self._error("action must be mount or eject")
                    self._json(self._state())
                else:
                    self._send(404, b"not found", "text/plain")
            except (ValueError, RuntimeError) as e:
                self._error(str(e))
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                log("api_error", path=path, error=repr(e))
                self._error(repr(e), 500)

        def _preview(self) -> None:
            self.send_response(200)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=FRAME")
            self.end_headers()
            with app.lock:
                app.camera.preview_clients += 1
            seq = -1
            try:
                while True:
                    frame, new_seq = app.camera.preview.wait_newer(seq)
                    if new_seq == seq:
                        continue  # timed out waiting, nothing new
                    seq = new_seq
                    if frame is None:
                        continue
                    self.wfile.write(b"--FRAME\r\nContent-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                with app.lock:
                    app.camera.preview_clients -= 1

        def log_message(self, format, *args) -> None:
            pass  # access logs would drown the JSON events

    class Server(socketserver.ThreadingMixIn, server.HTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    return Server(("", port), Handler)
