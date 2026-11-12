"""A stand-in for the platform, to run the detection mode without AWS (README.md, "The detection mode without AWS").

    python tools/dev_cloud.py <models-dir> [--config tools/dev-device-config.json] [--port 8100] [--ingest-status 202]

Serves the three endpoints the device uses, under one base URL (API_BASE_URL=http://localhost:8100):

  GET  /api/v1/device/config        the JSON file given by --config, re-read on every request; edit it to change
                                    the device's configuration (ETag and 304 as in device-management)
  GET  /api/v1/device/models        the versions of models.detector / models.ocr in that file, from <models-dir>
                                    laid out like the models bucket: <model>/<version>/<file>; 409 when missing
  POST /api/v1/ingest/detections    answers --ingest-status (202, or e.g. 503 / 400 to see retries / quarantine)
                                    and prints counts only, never plates (--show-plates to print them)

No token is checked or needed. Standard library only.
"""
import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REQUIRED_FILES = {"detector": ("model.onnx",), "ocr": ("model.onnx", "plate_config.yaml")}
FILES_PATH = "/files/"


def default_config() -> Path:
    """The service defaults of device-management (application.yaml) for this Pi: a stand-in until the device runs
    against the cloud, where device-management alone holds the configuration."""
    return Path(__file__).with_name("dev-device-config.json")


class DevCloud:
    def __init__(self, models_dir: Path, config_file: Path, ingest_status: int, show_plates: bool) -> None:
        self.models_dir = models_dir
        self.config_file = config_file
        self.ingest_status = ingest_status
        self.show_plates = show_plates

    def configuration(self) -> tuple[bytes, str]:
        body = self.config_file.read_bytes()
        return body, '"' + hashlib.sha256(body).hexdigest()[:16] + '"'

    def models(self) -> tuple[int, dict]:
        config = json.loads(self.config_file.read_bytes())
        versions = config["models"]
        expires = (datetime.now(UTC) + timedelta(minutes=30)).isoformat(timespec="seconds").replace("+00:00", "Z")
        answer = {"deviceId": config["deviceId"]}
        for model, file_names in REQUIRED_FILES.items():
            directory = self.models_dir / model / versions[model]
            if not all((directory / name).is_file() for name in file_names):
                return 409, {"code": "MODEL_NOT_PUBLISHED", "detail": f"{directory} lacks {', '.join(file_names)}"}
            answer[model] = {"version": versions[model], "files": [
                {"name": name, "sha256": hashlib.sha256((directory / name).read_bytes()).hexdigest(),
                 "sizeBytes": (directory / name).stat().st_size,
                 "url": f"{FILES_PATH}{model}/{versions[model]}/{name}", "expiresAt": expires}
                for name in file_names]}
        return 200, answer

    def model_file(self, relative: str) -> Path | None:
        path = (self.models_dir / relative).resolve()
        return path if path.is_file() and self.models_dir in path.parents else None


def handler(cloud: DevCloud):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/api/v1/device/config":
                body, etag = cloud.configuration()
                if self.headers.get("If-None-Match") == etag:
                    self._send(304, b"", {"ETag": etag})
                else:
                    self._send(200, body, {"ETag": etag, "Content-Type": "application/json"})
            elif path == "/api/v1/device/models":
                status, answer = cloud.models()
                self._json(status, answer)
            elif path.startswith(FILES_PATH) and (file := cloud.model_file(path[len(FILES_PATH):])):
                self._send(200, file.read_bytes(), {"Content-Type": "application/octet-stream"})
            else:
                self._json(404, {"code": "NOT_FOUND"})

        def do_POST(self):
            if self.path.split("?")[0] != "/api/v1/ingest/detections":
                self._json(404, {"code": "NOT_FOUND"})
                return
            batch = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            detections = batch.get("detections", [])
            report = {"batchId": batch.get("batchId"), "traceId": self.headers.get("X-Trace-Id"),
                      "detections": len(detections), "answer": cloud.ingest_status}
            if cloud.show_plates:
                report["plates"] = [d.get("plate") for d in detections]
            print(json.dumps(report), flush=True)
            accepted = {"batchId": batch.get("batchId"), "accepted": len(detections)}
            self._json(cloud.ingest_status, accepted if cloud.ingest_status < 300 else {"code": "DEV_CLOUD_REFUSED"})

        def _json(self, status: int, document: dict):
            self._send(status, json.dumps(document).encode(), {"Content-Type": "application/json"})

        def _send(self, status: int, body: bytes, headers: dict):
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # the access log would print presigned-looking paths for every file
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("models_dir", type=Path)
    parser.add_argument("--config", type=Path, default=default_config())
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to accept other machines (no auth!)")
    parser.add_argument("--ingest-status", type=int, default=202)
    parser.add_argument("--show-plates", action="store_true", help="print plate texts (personal data)")
    args = parser.parse_args()
    cloud = DevCloud(args.models_dir.resolve(), args.config.resolve(), args.ingest_status, args.show_plates)
    status, answer = cloud.models()
    print(json.dumps({"models": status, "detector": answer.get("detector", {}).get("version"),
                      "ocr": answer.get("ocr", {}).get("version"), "config": str(cloud.config_file)}), flush=True)
    print(f"API_BASE_URL=http://localhost:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), handler(cloud)).serve_forever()


if __name__ == "__main__":
    main()
