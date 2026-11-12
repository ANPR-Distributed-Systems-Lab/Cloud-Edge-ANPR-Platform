import hashlib
import json

import pytest

from detection.cloud.model_store import ManifestError, ModelStore, validate
from detection.cloud.transport import NetworkError
from fakes import FakeApi, response

MANIFEST_URL = "http://models.local/manifest.json"


def manifest(detector=b"det-v2", ocr=b"ocr-v3", config=b"cfg", detector_version="v2"):
    def entry(data, name):
        return {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "url": name}

    detector_url = f"detector/{detector_version}/model.onnx"
    return {"models": {
        "detector": {"version": detector_version, "files": {"model.onnx": entry(detector, detector_url)}},
        "ocr": {"version": "v3", "files": {"model.onnx": entry(ocr, "ocr/v3/model.onnx"),
                                           "plate_config.yaml": entry(config, "ocr/v3/plate_config.yaml")}},
    }}


def store(tmp_path, *answers, files=None):
    api = FakeApi(*answers)
    api.http.files = files or {}
    return ModelStore(tmp_path / "models", api, api.http, MANIFEST_URL), api


def served(detector=b"det-v2", detector_version="v2"):
    return {f"http://models.local/detector/{detector_version}/model.onnx": detector,
            "http://models.local/ocr/v3/model.onnx": b"ocr-v3",
            "http://models.local/ocr/v3/plate_config.yaml": b"cfg"}


def test_first_start_downloads_and_records_the_set(tmp_path):
    models_store, api = store(tmp_path, response(200, manifest()), files=served())
    models = models_store.prepare()
    assert models.versions == {"detector": "v2", "ocr": "v3"}
    assert models.detector.read_bytes() == b"det-v2" and models.ocr_config.read_bytes() == b"cfg"
    assert models.detector == tmp_path / "models" / "detector" / "v2" / "model.onnx"
    assert json.loads((tmp_path / "models" / "current.json").read_text())["ocr"]["version"] == "v3"
    assert not list((tmp_path / "models").rglob("*.part"))


def test_unchanged_files_are_not_downloaded_again(tmp_path):
    models_store, api = store(tmp_path, response(200, manifest()), response(200, manifest()), files=served())
    models_store.prepare()
    models_store.prepare()
    assert len(api.http.downloads) == 3


def test_without_network_the_cached_set_is_used(tmp_path):
    models_store, api = store(tmp_path, response(200, manifest()), NetworkError("offline"), files=served())
    first = models_store.prepare()
    assert models_store.prepare() == first


def test_without_network_and_cache_there_is_no_set(tmp_path):
    models_store, _ = store(tmp_path, NetworkError("offline"))
    assert models_store.prepare() is None


def test_a_corrupt_download_never_replaces_the_working_set(tmp_path):
    files = served() | {"http://models.local/detector/v3/model.onnx": b"truncated"}
    models_store, _ = store(tmp_path, response(200, manifest()),
                            response(200, manifest(detector=b"det-v3", detector_version="v3")), files=files)
    models_store.prepare()
    models = models_store.prepare()  # v3 fails its SHA-256: falls back to the cached v2
    assert models.versions["detector"] == "v2"
    assert not (tmp_path / "models" / "detector" / "v3" / "model.onnx").exists()


def test_an_update_keeps_the_previous_version_and_removes_older_ones(tmp_path):
    files = served() | served(b"det-v3", "v3") | served(b"det-v4", "v4")
    models_store, _ = store(tmp_path, response(200, manifest()),
                            response(200, manifest(detector=b"det-v3", detector_version="v3")),
                            response(200, manifest(detector=b"det-v4", detector_version="v4")), files=files)
    for _ in range(3):
        models = models_store.prepare()
    assert models.versions["detector"] == "v4"
    assert sorted(p.name for p in (tmp_path / "models" / "detector").iterdir()) == ["v3", "v4"]


def test_a_damaged_cached_file_is_not_used(tmp_path):
    models_store, _ = store(tmp_path, response(200, manifest()), NetworkError("offline"), files=served())
    models = models_store.prepare()
    models.ocr.write_bytes(b"bit rot")
    assert models_store.prepare() is None


@pytest.mark.parametrize("broken", [
    {},
    {"models": {"detector": {"version": "v2", "files": {}}}},
    {"models": manifest()["models"] | {"ocr": {"version": "../../etc", "files": {}}}},
    {"models": manifest()["models"] | {"detector": {"version": "v2", "files": {
        "model.onnx": {"sha256": "x" * 64, "url": "a"}}}}},
])
def test_invalid_manifests_are_refused(broken):
    with pytest.raises(ManifestError):
        validate(broken)
