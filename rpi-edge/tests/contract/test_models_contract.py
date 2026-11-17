import pytest
from samples import DEVICE_ID

from detection.cloud.model_store import REQUIRED_FILES
from detection.contract.configuration import ModelVersions
from detection.contract.models import DeviceModels
from detection.contract.parsing import ContractError

SHA = "ab" * 32


def file(name, url=None):
    return {"name": name, "sha256": SHA, "sizeBytes": 10, "url": url or f"https://s3/{name}?X-Amz-Signature=x",
            "expiresAt": "2026-11-12T10:30:00Z"}


def document(**override):
    return {"deviceId": DEVICE_ID,
            "detector": {"version": "v2", "files": [file("model.onnx")]},
            "ocr": {"version": "v3", "files": [file("model.onnx"), file("plate_config.yaml")]}} | override


def test_the_answer_maps_onto_typed_downloads():
    models = DeviceModels.from_document(document(), REQUIRED_FILES)
    assert models.versions == ModelVersions("v2", "v3")
    assert models.ocr.file("plate_config.yaml").size_bytes == 10
    assert models.detector.files[0].url.startswith("https://s3/")


@pytest.mark.parametrize("override, problem", [
    ({"ocr": {"version": "v3", "files": [file("model.onnx")]}}, "ocr.files has no plate_config.yaml"),
    ({"detector": {"version": "v2", "files": []}}, "detector.files must be a non-empty array"),
    ({"detector": {"version": "v2", "files": [file("../model.onnx")]}}, "detector.files[0].name must match"),
    ({"detector": {"version": "v2", "files": [file("model.onnx") | {"sha256": "x"}]}},
     "detector.files[0].sha256 must match"),
    ({"ocr": {"version": "../../etc", "files": [file("model.onnx"), file("plate_config.yaml")]}},
     "ocr.version must match"),
])
def test_answers_the_device_cannot_use_are_refused(override, problem):
    with pytest.raises(ContractError) as e:
        DeviceModels.from_document(document(**override), REQUIRED_FILES)
    assert any(p.startswith(problem) for p in e.value.problems)
