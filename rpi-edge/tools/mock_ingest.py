"""Stand-in for POST /api/v1/ingest/detections, for developing the detection mode without AWS.

    python tools/mock_ingest.py [--port 8200] [--status 202] [--show-plates]

Answers like the ingest Lambda (docs/api/ingest-detections.md, section 3) and logs one JSON line per batch.
--status makes it answer with that status instead (e.g. 503 to watch the retries, 400 for the quarantine).
Plate texts are personal data: they are printed only with --show-plates. Standard library only.
"""
import argparse
import json
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PATH = "/api/v1/ingest/detections"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8200)
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to accept other machines (no auth!)")
    parser.add_argument("--status", type=int, default=202)
    parser.add_argument("--show-plates", action="store_true")
    args = parser.parse_args()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            trace_id = self.headers.get("X-Trace-Id", "")
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                detections = body["detections"]
            except (ValueError, KeyError, TypeError):
                return self._answer(400, {"code": "INVALID_JSON", "requestId": trace_id})
            if self.path != PATH:
                return self._answer(404, {"code": "NOT_FOUND", "requestId": trace_id})
            line = {"ts": datetime.now(timezone.utc).isoformat(), "event": "batch_received", "traceId": trace_id,
                    "batchId": body.get("batchId"), "count": len(detections), "answer": args.status,
                    "authorization": "present" if self.headers.get("Authorization") else "none"}
            if args.show_plates:
                line["plates"] = [d.get("plate") for d in detections]
            print(json.dumps(line), flush=True)
            if args.status == 202:
                return self._answer(202, {"batchId": body.get("batchId"), "accepted": len(detections),
                                          "traceId": trace_id})
            return self._answer(args.status, {"code": "MOCK_FAILURE", "requestId": trace_id})

        def _answer(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json" if status < 400 else "application/problem+json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Trace-Id", payload.get("traceId") or payload.get("requestId") or "")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):  # the JSON line above replaces the default access log
            pass

    print(json.dumps({"event": "mock_ingest_listening", "port": args.port, "path": PATH, "status": args.status}),
          flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
