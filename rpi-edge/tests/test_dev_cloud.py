"""The development stand-in of the platform answers in the shapes the device parses and refuses what it would."""
import json
from datetime import UTC, datetime

from samples import DEVICE_ID, detection_event

from detection.cloud.model_store import REQUIRED_FILES
from detection.contract.alerts import AlertList
from detection.contract.configuration import DeviceConfiguration
from detection.contract.images import ImageUploadUrls, image_key
from detection.contract.locations import LocationPoint
from detection.contract.metrics import DeviceMetric, FixType, GpsState, QueueLengths
from detection.contract.models import DeviceModels
from tools.dev_cloud import DevCloud, check_detection, check_location_point, check_metric, default_config

CAPTURED = datetime(2026, 11, 13, 4, 5, 6, 789_000, tzinfo=UTC)
FRAME_ID = "0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b01"


def models_dir(tmp_path):
    files = {"detector/v2/model.onnx": b"d", "ocr/v3/model.onnx": b"o", "ocr/v3/plate_config.yaml": b"c"}
    for path, data in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(data)
    return tmp_path


def cloud(tmp_path, **kwargs):
    config = json.loads(default_config().read_bytes()) | {"deviceId": DEVICE_ID}
    (tmp_path / "config.json").write_text(json.dumps(config))
    return DevCloud(tmp_path, tmp_path / "config.json", 202, False, **kwargs)


def test_the_shipped_configuration_satisfies_the_contract():
    DeviceConfiguration.from_document(json.loads(default_config().read_bytes()))


def test_the_models_of_the_configuration_are_offered(tmp_path):
    status, answer = DevCloud(models_dir(tmp_path / "models"), default_config(), 202, False).models()
    assert status == 200
    models = DeviceModels.from_document(answer, REQUIRED_FILES)
    assert models.ocr.file("plate_config.yaml").url == "/files/ocr/v3/plate_config.yaml"


def test_model_files_are_served_only_from_the_models_directory(tmp_path):
    served = DevCloud(models_dir(tmp_path / "models"), default_config(), 202, False)
    assert served.model_file("ocr/v3/plate_config.yaml").read_bytes() == b"c"
    assert served.model_file("../../etc/passwd") is None


def test_a_missing_version_is_not_published(tmp_path):
    (tmp_path / "models").mkdir()
    status, answer = DevCloud(tmp_path / "models", default_config(), 202, False).models()
    assert status == 409 and answer["code"] == "MODEL_NOT_PUBLISHED"


def test_the_alert_list_has_the_shape_of_operations_service(tmp_path):
    (tmp_path / "alerts.json").write_text(json.dumps([{"alertId": "0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c",
                                                       "plate": "WA12345", "alertText": None}]))
    body, etag = cloud(tmp_path, alerts_file=tmp_path / "alerts.json").alerts()
    assert AlertList.from_document(json.loads(body)).items[0].plate == "WA12345"
    assert etag.startswith('W/"')
    empty, _ = cloud(tmp_path).alerts()
    assert AlertList.from_document(json.loads(empty)).items == ()


def test_what_the_device_sends_passes_the_checks_of_the_stand_in():
    assert check_detection(detection_event(1).to_document()) == []
    point = LocationPoint("0192f3a4-9a11-7d20-9c01-3b5d7f9a1c02", CAPTURED, 52.2, 21.0, 4.5, 10.0, 90.0)
    assert check_location_point(point.to_document()) == []
    metric = DeviceMetric(CAPTURED, 54.0, 30.0, 20.0, 1.7, QueueLengths(1, 2, 3), 1000, 60,
                          GpsState(FixType.FIX_3D, 9))
    assert check_metric(metric.to_document()) == []


def test_a_batch_with_a_problem_is_refused_whole_with_the_index_of_each_item(tmp_path):
    good = detection_event(1).to_document()
    bad = dict(good)
    del bad["location"]
    bad["imageKey"] = "photos/a.jpg"
    status, answer = cloud(tmp_path).ingest("detections", [good, bad], check_detection, 202)
    assert status == 400 and answer["code"] == "VALIDATION_FAILED"
    assert {(f["index"], f["field"], f["code"]) for f in answer["fields"]} == {
        (1, "detections[1].location", "REQUIRED"), (1, "detections[1].imageKey", "FORMAT")}
    assert cloud(tmp_path).ingest("detections", [good], check_detection, 202)[0] == 202
    assert cloud(tmp_path).ingest("metrics", [], check_metric, 204)[0] == 204


def test_a_position_of_zero_zero_or_out_of_range_is_refused():
    assert check_location_point({"locationId": "x", "recordedAt": "x", "lat": 0, "lon": 0}) == [
        ("", "INVALID_LOCATION")]
    assert check_location_point({"locationId": "x", "recordedAt": "x", "lat": 91, "lon": 0}) == [("lat", "RANGE")]
    assert check_location_point({"locationId": "x", "recordedAt": "x", "lat": 1, "lon": 1, "headingDeg": 360}) == [
        ("headingDeg", "RANGE")]


def test_upload_urls_carry_the_key_of_the_contract_and_photos_are_kept(tmp_path):
    stand_in = cloud(tmp_path, uploads_dir=tmp_path / "photos")
    status, answer = stand_in.presigned_urls([{"frameId": FRAME_ID, "capturedAt": "2026-11-13T04:05:06.789Z"}],
                                             "http://localhost:8100")
    upload = ImageUploadUrls.from_document(answer).uploads[0]
    assert status == 200 and upload.image_key == image_key(DEVICE_ID, FRAME_ID, CAPTURED)
    assert upload.upload_url == f"http://localhost:8100/upload/{upload.image_key}"
    assert stand_in.keep_photo(upload.image_key, "image/jpeg", b"jpeg") == 200
    assert (tmp_path / "photos" / upload.image_key).read_bytes() == b"jpeg"
    assert stand_in.keep_photo(upload.image_key, "text/plain", b"x") == 403  # not the signed Content-Type
    assert stand_in.keep_photo("photos/a.jpg", "image/jpeg", b"x") == 403
