"""A stand-in for the platform, to run the detection mode without AWS (README.md, "The detection mode without AWS").

    python tools/dev_cloud.py <models-dir> [--config tools/dev-device-config.json] [--alerts FILE] [--uploads DIR]
                              [--port 8100] [--ingest-status 202]

Serves the endpoints the device uses, under one base URL (API_BASE_URL=http://localhost:8100):

  GET  /api/v1/device/config          the JSON file given by --config, re-read on every request; edit it to change
                                      the device's configuration (ETag and 304 as in device-management)
  GET  /api/v1/device/models          the versions of models.detector / models.ocr in that file, from <models-dir>
                                      laid out like the models bucket: <model>/<version>/<file>; 409 when missing
  GET  /api/v1/alerts                 the alert list of operations-service (AlertPage) from the JSON file given by
                                      --alerts, re-read on every request (ETag and 304); an empty list without it.
                                      The file holds plates: keep it outside the repository.
  POST /api/v1/ingest/detections      checks the batch against the main rules of the ingest contract (required fields,
  POST /api/v1/ingest/device-locations  ranges, the format of imageKey) and answers 400 with fields[] when it breaks
  POST /api/v1/device/metrics         them, otherwise --ingest-status (202, or e.g. 503 to see the retries; metrics
                                      answer 204). Prints counts only, never plates or coordinates.
  POST /api/v1/images/presigned-urls  an upload URL per frame, for the key the contract fixes (device and capture date)
  PUT  /upload/<key>                  receives a photo (Content-Type image/jpeg); kept in --uploads when given: it
                                      shows plates, keep that folder outside the repository.

No token is checked or needed. Standard library only.
"""
import argparse
import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REQUIRED_FILES = {"detector": ("model.onnx",), "ocr": ("model.onnx", "plate_config.yaml")}
FILES_PATH = "/files/"
UPLOAD_PATH = "/upload/"
UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
IMAGE_KEY = re.compile(rf"images/(?P<device>{UUID})/\d{{4}}/\d{{2}}/\d{{2}}/(?P<frame>{UUID})\.jpg")
FieldProblems = list[tuple[str, str]]  # (field, code), as in fields[] of an error


def default_config() -> Path:
    """The service defaults of device-management (application.yaml) for this Pi: a stand-in until the device runs
    against the cloud, where device-management alone holds the configuration."""
    return Path(__file__).with_name("dev-device-config.json")


def check_detection(d: dict) -> FieldProblems:
    problems = [(f, "REQUIRED") for f in ("detectionId", "frameId", "detectedAt", "plate", "ocrConfidence",
                                          "detectorConfidence", "imageKey", "corners", "location") if f not in d]
    key = IMAGE_KEY.fullmatch(str(d.get("imageKey", "")))
    names_its_frame = key is not None and key["frame"].lower() == str(d.get("frameId", "")).lower()
    if "imageKey" in d and not names_its_frame:
        problems.append(("imageKey", "FORMAT"))
    return problems + check_position(d["location"], "location") if "location" in d else problems


def check_location_point(p: dict) -> FieldProblems:
    problems = [(f, "REQUIRED") for f in ("locationId", "recordedAt", "lat", "lon") if f not in p]
    heading = p.get("headingDeg")
    if heading is not None and not 0 <= heading < 360:
        problems.append(("headingDeg", "RANGE"))
    return problems + check_position(p, "")


def check_position(position, prefix: str) -> FieldProblems:
    if not isinstance(position, dict):
        return [(prefix, "TYPE")]
    name = f"{prefix}." if prefix else ""
    lat, lon = position.get("lat"), position.get("lon")
    if lat is None:
        return [(f"{name}lat", "REQUIRED")]
    if lon is None:
        return [(f"{name}lon", "REQUIRED")]
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return [(f"{name}lat", "RANGE")]
    return [(name.rstrip("."), "INVALID_LOCATION")] if (lat, lon) == (0, 0) else []


def check_metric(m: dict) -> FieldProblems:
    required = ("recordedAt", "cpuTemperatureC", "cpuUsagePercent", "ramUsagePercent", "processingFps", "queues",
                "diskFreeMb", "uptimeSeconds", "gps")
    problems = [(f, "REQUIRED") for f in required if f not in m]
    ranges = {"cpuTemperatureC": (-40, 125), "cpuUsagePercent": (0, 100), "ramUsagePercent": (0, 100)}
    return problems + [(f, "RANGE") for f, (low, high) in ranges.items() if f in m and not low <= m[f] <= high]


class DevCloud:
    def __init__(self, models_dir: Path, config_file: Path, ingest_status: int, show_plates: bool,
                 alerts_file: Path | None = None, uploads_dir: Path | None = None) -> None:
        self.models_dir = models_dir
        self.config_file = config_file
        self.ingest_status = ingest_status
        self.show_plates = show_plates
        self.alerts_file = alerts_file
        self.uploads_dir = uploads_dir

    @property
    def device_id(self) -> str:
        return json.loads(self.config_file.read_bytes())["deviceId"]

    def configuration(self) -> tuple[bytes, str]:
        return _with_etag(self.config_file.read_bytes())

    def alerts(self) -> tuple[bytes, str]:
        items = json.loads(self.alerts_file.read_bytes()) if self.alerts_file else []
        page = {"items": items, "page": {"page": 0, "size": len(items), "totalElements": len(items), "totalPages": 1}}
        return _with_etag(json.dumps(page).encode())

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

    def ingest(self, name: str, items: list[dict], check: Callable[[dict], FieldProblems],
               success: int) -> tuple[int, dict]:
        """Answers a batch like the platform: all or nothing, with the index of every offending item."""
        fields = [{"index": i, "field": f"{name}[{i}].{field}".rstrip("."), "code": code}
                  for i, item in enumerate(items) for field, code in check(item)]
        if fields:
            return 400, {"code": "VALIDATION_FAILED", "fields": fields}
        status = self.ingest_status if self.ingest_status != 202 else success
        return status, {"accepted": len(items)} if status < 300 else {"code": "DEV_CLOUD_REFUSED"}

    def presigned_urls(self, frames: list[dict], base_url: str) -> tuple[int, dict]:
        uploads = []
        for frame in frames:
            captured = datetime.strptime(frame["capturedAt"], "%Y-%m-%dT%H:%M:%S.%fZ")
            key = f"images/{self.device_id}/{captured:%Y/%m/%d}/{frame['frameId']}.jpg"
            expires = (datetime.now(UTC) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            uploads.append({"frameId": frame["frameId"], "imageKey": key,
                            "uploadUrl": f"{base_url}{UPLOAD_PATH}{key}", "expiresAt": expires})
        return 200, {"uploads": uploads}

    def keep_photo(self, key: str, content_type: str, body: bytes) -> int:
        if content_type != "image/jpeg" or not IMAGE_KEY.fullmatch(key):
            return 403  # S3 refuses a PUT whose Content-Type is not the one that was signed
        if self.uploads_dir:
            target = self.uploads_dir / key
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        return 200


def _with_etag(body: bytes) -> tuple[bytes, str]:
    return body, 'W/"' + hashlib.sha256(body).hexdigest()[:16] + '"'


def handler(cloud: DevCloud):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/api/v1/device/config", "/api/v1/alerts"):
                body, etag = cloud.configuration() if path.endswith("config") else cloud.alerts()
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
            path = self.path.split("?")[0]
            body = json.loads(self._body() or b"{}")
            base_url = f"http://{self.headers.get('Host', 'localhost')}"
            if path == "/api/v1/ingest/detections":
                status, answer = cloud.ingest("detections", body.get("detections", []), check_detection, 202)
                self._report("detections", body, status, len(body.get("detections", [])),
                             [d.get("plate") for d in body.get("detections", [])] if cloud.show_plates else None)
            elif path == "/api/v1/ingest/device-locations":
                status, answer = cloud.ingest("locations", body.get("locations", []), check_location_point, 202)
                self._report("locations", body, status, len(body.get("locations", [])))
            elif path == "/api/v1/device/metrics":
                status, answer = cloud.ingest("metrics", body.get("metrics", []), check_metric, 204)
                self._report("metrics", body, status, len(body.get("metrics", [])))
            elif path == "/api/v1/images/presigned-urls":
                status, answer = cloud.presigned_urls(body.get("frames", []), base_url)
                self._report("image-urls", body, status, len(body.get("frames", [])))
            else:
                status, answer = 404, {"code": "NOT_FOUND"}
            if answer and status != 204:
                self._json(status, answer)
            else:
                self._send(status, b"", {})

        def do_PUT(self):
            path = self.path.split("?")[0]
            if not path.startswith(UPLOAD_PATH):
                self._json(404, {"code": "NOT_FOUND"})
                return
            data = self._body()
            status = cloud.keep_photo(path[len(UPLOAD_PATH):], self.headers.get("Content-Type", ""), data)
            print(json.dumps({"stream": "photo", "bytes": len(data), "answer": status}), flush=True)
            self._send(status, b"", {})

        def _body(self) -> bytes:
            return self.rfile.read(int(self.headers.get("Content-Length", 0)))

        def _report(self, stream: str, body: dict, status: int, count: int, plates: list | None = None):
            report = {"stream": stream, "traceId": self.headers.get("X-Trace-Id"), "batchId": body.get("batchId"),
                      "items": count, "answer": status}
            if plates is not None:
                report["plates"] = plates
            print(json.dumps(report), flush=True)

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
    parser.add_argument("--alerts", type=Path, help="JSON array of AlertResponse items (holds plates)")
    parser.add_argument("--uploads", type=Path, help="keep the uploaded photos here (they show plates)")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to accept other machines (no auth!)")
    parser.add_argument("--ingest-status", type=int, default=202)
    parser.add_argument("--show-plates", action="store_true", help="print plate texts (personal data)")
    args = parser.parse_args()
    cloud = DevCloud(args.models_dir.resolve(), args.config.resolve(), args.ingest_status, args.show_plates,
                     args.alerts.resolve() if args.alerts else None, args.uploads.resolve() if args.uploads else None)
    status, answer = cloud.models()
    print(json.dumps({"models": status, "detector": answer.get("detector", {}).get("version"),
                      "ocr": answer.get("ocr", {}).get("version"), "config": str(cloud.config_file)}), flush=True)
    print(f"API_BASE_URL=http://localhost:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), handler(cloud)).serve_forever()


if __name__ == "__main__":
    main()
