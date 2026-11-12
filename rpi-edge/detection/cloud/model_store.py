"""The models the detection mode runs, downloaded at startup and cached on the SD card (DETECTION.md, "Models").

The manifest (GET /api/v1/device/models of device-management, or a development server) names the current
version of each model and, per file, its SHA-256, size and a download URL (a presigned S3 URL, or one relative
to the manifest):

  {"models": {"detector": {"version": "v2", "files": {"model.onnx": {"sha256": "...", "size": 1, "url": "..."}}},
              "ocr": {"version": "v3", "files": {"model.onnx": {...}, "plate_config.yaml": {...}}}}}

Versions are immutable, so a file is downloaded once into models/<name>/<version>/ and checked against its
SHA-256. models/current.json records the last complete set and is replaced only after every file is in place:
a power cut or a network error during a download never leaves the device with a half-installed set. Without
network the cached set is used; without a cached set the mode waits and retries.
"""
import hashlib
import json
import os
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

from common.files import write_json_atomic
from common.jsonlog import log
from detection.cloud.api import Api
from detection.cloud.cognito import AuthError
from detection.cloud.transport import Http, NetworkError
from detection.delivery.events import uuid7

REQUIRED = {"detector": ("model.onnx",), "ocr": ("model.onnx", "plate_config.yaml")}
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")  # versions and file names become paths
RETRY_FIRST_SECONDS = 5.0
RETRY_MAX_SECONDS = 300.0


class ManifestError(Exception):
    pass


@dataclass(frozen=True)
class ModelSet:
    detector: Path
    ocr: Path
    ocr_config: Path
    versions: dict  # name -> version


def validate(manifest) -> dict:
    """The manifest's models, checked enough to be turned into paths and downloads."""
    models = manifest.get("models") if isinstance(manifest, dict) else None
    if not isinstance(models, dict):
        raise ManifestError("no models")
    for name, files in REQUIRED.items():
        model = models.get(name)
        if not isinstance(model, dict) or not SAFE_NAME.fullmatch(str(model.get("version", ""))):
            raise ManifestError(f"{name}: missing or invalid version")
        listed = model.get("files")
        if not isinstance(listed, dict) or any(f not in listed for f in files):
            raise ManifestError(f"{name}: needs files {files}")
        for file_name, meta in listed.items():
            if not SAFE_NAME.fullmatch(file_name) or not isinstance(meta, dict):
                raise ManifestError(f"{name}: invalid file entry {file_name!r}")
            if not re.fullmatch(r"[0-9a-f]{64}", str(meta.get("sha256", ""))):
                raise ManifestError(f"{name}/{file_name}: invalid sha256")
            if not isinstance(meta.get("url"), str) or not meta["url"]:
                raise ManifestError(f"{name}/{file_name}: no url")
    return {name: models[name] for name in REQUIRED}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ModelStore:
    def __init__(self, root: Path, api: Api, http: Http, manifest_url: str | None) -> None:
        self.root = root
        self.api = api
        self.http = http
        self.manifest_url = manifest_url
        self.current_file = root / "current.json"

    def wait_for_models(self, stop: threading.Event) -> ModelSet | None:
        """Blocks until a usable set exists (None if stopped first)."""
        delay = RETRY_FIRST_SECONDS
        while not stop.is_set():
            models = self.prepare()
            if models is not None:
                return models
            log("models_unavailable", level="error", retry_in_s=delay,
                hint="no cached models and the manifest cannot be fetched")
            stop.wait(delay)
            delay = min(delay * 2, RETRY_MAX_SECONDS)
        return None

    def prepare(self) -> ModelSet | None:
        """The current set of the manifest, installed if needed; the cached set when that fails; else None."""
        if self.manifest_url:
            try:
                return self._install(self._fetch_manifest())
            except (NetworkError, AuthError, ManifestError, OSError) as e:
                log("models_update_failed", level="warning", error=str(e))
        cached = self._cached()
        if cached is not None:
            log("models_from_cache", versions=cached.versions)
        return cached

    def _fetch_manifest(self) -> dict:
        response = self.api.request("GET", self.manifest_url, trace_id=uuid7())
        if response.status != 200:
            raise ManifestError(f"manifest: HTTP {response.status}")
        try:
            return validate(response.json())
        except ValueError:
            raise ManifestError("manifest is not JSON") from None

    def _install(self, models: dict) -> ModelSet:
        for name, model in models.items():
            for file_name, meta in model["files"].items():
                self._download_if_missing(name, model["version"], file_name, meta)
        previous = self._read_current()
        current = {name: {"version": m["version"], "files": {f: {"sha256": meta["sha256"]}
                                                             for f, meta in m["files"].items()}}
                   for name, m in models.items()}
        write_json_atomic(self.current_file, current)  # only now does the new set replace the old one
        self._remove_old_versions(keep=[current, previous or {}])
        log("models_ready", versions={name: m["version"] for name, m in current.items()})
        return self._model_set(current)

    def _download_if_missing(self, name: str, version: str, file_name: str, meta: dict) -> None:
        target = self.root / name / version / file_name
        if target.exists() and sha256_of(target) == meta["sha256"]:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        digest = self.http.download(urljoin(self.manifest_url, meta["url"]), part)
        if digest != meta["sha256"]:
            part.unlink(missing_ok=True)
            raise ManifestError(f"{name}/{file_name}: SHA-256 mismatch")
        os.replace(part, target)
        log("model_file_downloaded", model=name, version=version, file=file_name, bytes=target.stat().st_size)

    def _read_current(self) -> dict | None:
        try:
            with open(self.current_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _cached(self) -> ModelSet | None:
        """The recorded set, if every file is still there and intact."""
        current = self._read_current()
        if not isinstance(current, dict) or any(name not in current for name in REQUIRED):
            return None
        for name, model in current.items():
            for file_name, meta in model["files"].items():
                path = self.root / name / model["version"] / file_name
                if not path.exists() or sha256_of(path) != meta["sha256"]:
                    log("cached_model_damaged", level="error", model=name, file=file_name)
                    return None
        return self._model_set(current)

    def _model_set(self, current: dict) -> ModelSet:
        detector = self.root / "detector" / current["detector"]["version"]
        ocr = self.root / "ocr" / current["ocr"]["version"]
        return ModelSet(detector / "model.onnx", ocr / "model.onnx", ocr / "plate_config.yaml",
                        {name: m["version"] for name, m in current.items()})

    def _remove_old_versions(self, keep: list[dict]) -> None:
        """Keeps the current and the previous version of each model, so a bad update can be rolled back."""
        for name in REQUIRED:
            wanted = {k[name]["version"] for k in keep if name in k}
            for directory in (self.root / name).iterdir():
                if directory.is_dir() and directory.name not in wanted:
                    shutil.rmtree(directory, ignore_errors=True)
