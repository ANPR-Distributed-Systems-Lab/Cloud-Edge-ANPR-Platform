import hashlib
import json

import pytest
from fakes import FakeApi, response
from samples import DEVICE_ID

from detection.cloud.model_store import ModelStore, ModelsUnavailable
from detection.cloud.transport import NetworkError
from detection.contract.configuration import ModelVersions

MODELS_URL = "https://api.example/api/v1/device/models"
S3 = "https://models.s3.example/models"


def answer(detector=b"det-v2", detector_version="v2"):
    """GET /api/v1/device/models for detector <detector_version> and ocr v3, with presigned-looking URLs."""
    def entry(name, data, path):
        return {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "sizeBytes": len(data),
                "url": f"{S3}/{path}?X-Amz-Signature=s", "expiresAt": "2026-11-12T10:30:00Z"}

    return {"deviceId": DEVICE_ID,
            "detector": {"version": detector_version,
                         "files": [entry("model.onnx", detector, f"detector/{detector_version}/model.onnx")]},
            "ocr": {"version": "v3", "files": [entry("model.onnx", b"ocr-v3", "ocr/v3/model.onnx"),
                                               entry("plate_config.yaml", b"cfg", "ocr/v3/plate_config.yaml")]}}


def served(detector=b"det-v2", detector_version="v2"):
    return {f"{S3}/detector/{detector_version}/model.onnx?X-Amz-Signature=s": detector,
            f"{S3}/ocr/v3/model.onnx?X-Amz-Signature=s": b"ocr-v3",
            f"{S3}/ocr/v3/plate_config.yaml?X-Amz-Signature=s": b"cfg"}


def store(tmp_path, *answers, files=None):
    api = FakeApi(*answers)
    api.http.files = files or {}
    return ModelStore(tmp_path / "models", api, api.http, MODELS_URL), api


def test_a_set_is_downloaded_checked_and_recorded(tmp_path):
    models_store, api = store(tmp_path, response(200, answer()), files=served())
    model_set = models_store.install(models_store.fetch())
    assert model_set.versions == ModelVersions("v2", "v3")
    assert model_set.detector.read_bytes() == b"det-v2" and model_set.ocr_config.read_bytes() == b"cfg"
    assert model_set.detector == tmp_path / "models" / "detector" / "v2" / "model.onnx"
    assert json.loads((tmp_path / "models" / "current.json").read_text())["ocr"]["version"] == "v3"
    assert not list((tmp_path / "models").rglob("*.part"))
    assert models_store.cached() == model_set


def test_files_already_in_the_cache_are_not_downloaded_again(tmp_path):
    models_store, api = store(tmp_path, response(200, answer()), response(200, answer()), files=served())
    models_store.install(models_store.fetch())
    models_store.install(models_store.fetch())
    assert len(api.http.downloads) == 3


@pytest.mark.parametrize("failure", [NetworkError("offline"), response(409, {"code": "MODEL_NOT_PUBLISHED"}),
                                     response(200, {"detector": {}})])
def test_an_unusable_answer_is_reported_as_unavailable(tmp_path, failure):
    models_store, _ = store(tmp_path, failure)
    with pytest.raises(ModelsUnavailable):
        models_store.fetch()


def test_a_corrupt_download_never_replaces_the_installed_set(tmp_path):
    files = served() | {f"{S3}/detector/v3/model.onnx?X-Amz-Signature=s": b"truncated"}
    models_store, _ = store(tmp_path, response(200, answer()),
                            response(200, answer(detector=b"det-v3", detector_version="v3")), files=files)
    models_store.install(models_store.fetch())
    with pytest.raises(ModelsUnavailable, match="SHA-256"):
        models_store.install(models_store.fetch())
    assert models_store.cached().versions.detector == "v2"
    assert not (tmp_path / "models" / "detector" / "v3" / "model.onnx").exists()


def test_an_update_keeps_the_previous_version_and_removes_older_ones(tmp_path):
    files = served() | served(b"det-v3", "v3") | served(b"det-v4", "v4")
    models_store, _ = store(tmp_path, response(200, answer()),
                            response(200, answer(detector=b"det-v3", detector_version="v3")),
                            response(200, answer(detector=b"det-v4", detector_version="v4")), files=files)
    for _ in range(3):
        model_set = models_store.install(models_store.fetch())
    assert model_set.versions.detector == "v4"
    assert sorted(p.name for p in (tmp_path / "models" / "detector").iterdir()) == ["v3", "v4"]


def test_a_damaged_cached_file_is_not_used(tmp_path):
    models_store, _ = store(tmp_path, response(200, answer()), files=served())
    model_set = models_store.install(models_store.fetch())
    model_set.ocr.write_bytes(b"bit rot")
    assert models_store.cached() is None


def test_an_empty_cache_has_no_set(tmp_path):
    models_store, _ = store(tmp_path)
    assert models_store.cached() is None
