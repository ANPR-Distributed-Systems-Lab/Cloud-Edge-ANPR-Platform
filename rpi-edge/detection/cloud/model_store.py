"""The model cache on the SD card (DETECTION.md, "Models"): downloads, checks and installs model versions.

GET /api/v1/device/models (contract/models.py) names the versions of the device's configuration and gives, per
file, its SHA-256, size and a presigned URL. Versions are immutable, so a file is downloaded once into
models/<model>/<version>/ and checked against its SHA-256. models/current.json records the last complete set
and is replaced only after every file is in place: a power cut or a network error during a download never
leaves the device with a half-installed set. The current and the previous version of each model are kept.
"""
import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin

from common.files import write_json_atomic
from common.jsonlog import log
from detection.cloud.api import Api
from detection.cloud.cognito import AuthError
from detection.cloud.transport import Http, NetworkError
from detection.contract.configuration import ModelVersions
from detection.contract.models import DeviceModels, ModelFile
from detection.contract.parsing import ContractError
from detection.contract.problem import Problem
from detection.contract.wire import uuid7
from detection.vision.models import ModelSet

# What the device needs of each model; ml-models publishes these files (anpr-publish-model).
REQUIRED_FILES = {"detector": ("model.onnx",), "ocr": ("model.onnx", "plate_config.yaml")}
CURRENT_FILE = "current.json"


class ModelsUnavailable(Exception):
    """The models could not be fetched or installed now; the caller keeps what it has and retries later."""


@dataclass(frozen=True)
class InstalledModel:
    """One model of current.json: its version and the SHA-256 of each file, to re-check the cache at startup."""
    version: str
    sha256: dict[str, str]  # file name -> SHA-256


class ModelStore:
    def __init__(self, root: Path, api: Api, http: Http, models_url: str) -> None:
        self.root = root
        self.api = api
        self.http = http
        self.models_url = models_url

    def fetch(self) -> DeviceModels:
        """The download URLs of the versions in the configuration of the device."""
        trace_id = uuid7()
        try:
            response = self.api.request("GET", self.models_url, trace_id=trace_id)
        except (NetworkError, AuthError) as e:
            raise ModelsUnavailable(str(e)) from None
        if response.status != 200:
            problem = Problem.of(response.status, response.body)
            raise ModelsUnavailable(f"HTTP {response.status} {problem.code or ''}".strip())
        try:
            return DeviceModels.from_document(response.json(), REQUIRED_FILES)
        except (ContractError, ValueError) as e:
            raise ModelsUnavailable(f"invalid answer: {e}") from None

    def install(self, models: DeviceModels) -> ModelSet:
        """Downloads what is missing, then records the set as current. Raises ModelsUnavailable."""
        for name in REQUIRED_FILES:
            download = getattr(models, name)
            for file in download.files:
                self._download_if_missing(name, download.version, file)
        previous = self._read_current()
        current = {name: InstalledModel(getattr(models, name).version,
                                        {f.name: f.sha256 for f in getattr(models, name).files})
                   for name in REQUIRED_FILES}
        write_json_atomic(self.root / CURRENT_FILE, {name: asdict(m) for name, m in current.items()})
        self._remove_old_versions(keep=[current, previous or {}])
        return self._model_set(current)

    def cached(self) -> ModelSet | None:
        """The recorded set, if every file is still there and intact."""
        current = self._read_current()
        if current is None:
            return None
        for name, model in current.items():
            for file_name, sha256 in model.sha256.items():
                path = self.root / name / model.version / file_name
                if not path.exists() or sha256_of(path) != sha256:
                    log("cached_model_damaged", level="error", model=name, file=file_name)
                    return None
        return self._model_set(current)

    def _download_if_missing(self, name: str, version: str, file: ModelFile) -> None:
        target = self.root / name / version / file.name
        if target.exists() and sha256_of(target) == file.sha256:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        try:
            digest = self.http.download(urljoin(self.models_url, file.url), part)
        except (NetworkError, OSError) as e:
            part.unlink(missing_ok=True)
            raise ModelsUnavailable(f"{name}/{file.name}: {e}") from None
        if digest != file.sha256:
            part.unlink(missing_ok=True)
            raise ModelsUnavailable(f"{name}/{file.name}: SHA-256 mismatch")
        os.replace(part, target)
        log("model_file_downloaded", model=name, version=version, file=file.name, bytes=target.stat().st_size)

    def _read_current(self) -> dict[str, InstalledModel] | None:
        try:
            with open(self.root / CURRENT_FILE, encoding="utf-8") as f:
                document = json.load(f)
            return {name: InstalledModel(document[name]["version"], dict(document[name]["sha256"]))
                    for name in REQUIRED_FILES}
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _model_set(self, current: dict[str, InstalledModel]) -> ModelSet:
        detector = self.root / "detector" / current["detector"].version
        ocr = self.root / "ocr" / current["ocr"].version
        return ModelSet(ModelVersions(current["detector"].version, current["ocr"].version),
                        detector / "model.onnx", ocr / "model.onnx", ocr / "plate_config.yaml")

    def _remove_old_versions(self, keep: list[dict[str, InstalledModel]]) -> None:
        """Keeps the current and the previous version of each model, so going back is a download away at most."""
        for name in REQUIRED_FILES:
            wanted = {k[name].version for k in keep if name in k}
            for directory in (self.root / name).iterdir():
                if directory.is_dir() and directory.name not in wanted:
                    shutil.rmtree(directory, ignore_errors=True)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
