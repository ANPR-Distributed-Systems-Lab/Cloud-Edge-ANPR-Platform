"""Serves model files with a manifest in the shape of GET /api/v1/device/models, for development without S3.

    python tools/serve_models.py <directory> [--port 8100]

<directory> holds one version of each model, laid out like the S3 keys (DETECTION.md, "Models"):
    detector/<version>/model.onnx
    ocr/<version>/model.onnx
    ocr/<version>/plate_config.yaml
The manifest is at /manifest.json; its file URLs are relative to it. Standard library only.
"""
import argparse
import functools
import hashlib
import json
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def build_manifest(root: Path) -> dict:
    models = {}
    for model_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        versions = [v for v in model_dir.iterdir() if v.is_dir()]
        if len(versions) != 1:
            sys.exit(f"{model_dir}: expected exactly one version directory, found {[v.name for v in versions]}")
        version = versions[0]
        files = {}
        for path in sorted(p for p in version.iterdir() if p.is_file()):
            files[path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size,
                                "url": f"{model_dir.name}/{version.name}/{path.name}"}
        models[model_dir.name] = {"version": version.name, "files": files}
    return {"models": models}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to accept other machines (no auth!)")
    args = parser.parse_args()
    root = args.directory.resolve()
    manifest = json.dumps(build_manifest(root), indent=2).encode()

    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] == "/manifest.json":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(manifest)))
                self.end_headers()
                self.wfile.write(manifest)
                return
            super().do_GET()

    print(json.loads(manifest), flush=True)
    print(f"serving {root} on port {args.port}: http://<host>:{args.port}/manifest.json", flush=True)
    ThreadingHTTPServer((args.host, args.port), functools.partial(Handler, directory=str(root))).serve_forever()


if __name__ == "__main__":
    main()
