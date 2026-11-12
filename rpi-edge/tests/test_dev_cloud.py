"""The development stand-in of the platform answers in the shapes the device parses."""
import json

from detection.cloud.model_store import REQUIRED_FILES
from detection.contract.configuration import DeviceConfiguration
from detection.contract.models import DeviceModels
from tools.dev_cloud import DevCloud, default_config


def models_dir(tmp_path):
    files = {"detector/v2/model.onnx": b"d", "ocr/v3/model.onnx": b"o", "ocr/v3/plate_config.yaml": b"c"}
    for path, data in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(data)
    return tmp_path


def test_the_shipped_configuration_satisfies_the_contract():
    DeviceConfiguration.from_document(json.loads(default_config().read_bytes()))


def test_the_models_of_the_configuration_are_offered(tmp_path):
    cloud = DevCloud(models_dir(tmp_path / "models"), default_config(), 202, False)
    status, answer = cloud.models()
    assert status == 200
    models = DeviceModels.from_document(answer, REQUIRED_FILES)
    assert models.ocr.file("plate_config.yaml").url == "/files/ocr/v3/plate_config.yaml"
    assert cloud.model_file("ocr/v3/plate_config.yaml").read_bytes() == b"c"
    assert cloud.model_file("../../etc/passwd") is None


def test_a_missing_version_is_not_published(tmp_path):
    (tmp_path / "models").mkdir()
    status, answer = DevCloud(tmp_path / "models", default_config(), 202, False).models()
    assert status == 409 and answer["code"] == "MODEL_NOT_PUBLISHED"
