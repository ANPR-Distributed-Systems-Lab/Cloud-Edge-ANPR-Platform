import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from anpr_ml.detector.export import MAX_CORNER_DIFF_PX, compare_frame
from anpr_ml.publish import build_release, key, publish, sha256_of

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


class FakeS3:
    """The three calls of boto3's S3 client that publish() makes, in memory."""

    def __init__(self, existing=()):
        self.objects = {k: b"" for k in existing}

    def head_object(self, Bucket, Key):
        from botocore.exceptions import ClientError

        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {}

    def upload_file(self, path, bucket, object_key):
        self.objects[object_key] = Path(path).read_bytes()

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body


def ocr_run(tmp_path):
    run = tmp_path / "ocr" / "v3"
    run.mkdir(parents=True)
    (run / "model.onnx").write_bytes(b"onnx bytes")
    (run / "plate_config.yaml").write_bytes(b"max_plate_slots: 10\n")
    return run


def test_the_release_lists_the_files_with_their_checksums(tmp_path):
    run = ocr_run(tmp_path)
    release = build_release("ocr", "v3", run, NOW)
    document = json.loads(release.to_json())
    assert document["model"] == "ocr" and document["version"] == "v3"
    assert document["publishedAt"] == "2026-11-12T10:00:00Z"
    assert document["files"] == [
        {"name": "model.onnx", "sha256": sha256_of(run / "model.onnx"), "sizeBytes": 10},
        {"name": "plate_config.yaml", "sha256": sha256_of(run / "plate_config.yaml"), "sizeBytes": 20},
    ]


def test_a_run_without_its_export_cannot_be_released(tmp_path):
    run = tmp_path / "detector" / "v2"
    run.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="anpr-export-detector"):
        build_release("detector", "v2", run, NOW)


def test_publish_uploads_the_files_then_the_release(tmp_path):
    pytest.importorskip("botocore")
    run = ocr_run(tmp_path)
    s3 = FakeS3()
    publish(s3, "bucket", build_release("ocr", "v3", run, NOW), run)
    assert list(s3.objects) == [key("ocr", "v3", "model.onnx"), key("ocr", "v3", "plate_config.yaml"),
                                "models/ocr/v3/release.json"]
    assert s3.objects["models/ocr/v3/model.onnx"] == b"onnx bytes"


def test_a_published_version_is_never_replaced(tmp_path):
    pytest.importorskip("botocore")
    run = ocr_run(tmp_path)
    s3 = FakeS3(existing=["models/ocr/v3/release.json"])
    with pytest.raises(FileExistsError):
        publish(s3, "bucket", build_release("ocr", "v3", run, NOW), run)
    assert list(s3.objects) == ["models/ocr/v3/release.json"]


def onnx_rows(*detections):
    """Export output rows (MAX_DET x 18) for (confidence, corners 4x2) pairs; the rest is padding."""
    rows = np.zeros((100, 18), np.float32)
    for i, (conf, corners) in enumerate(detections):
        rows[i, 4] = conf
        rows[i, 6:18] = np.hstack([np.asarray(corners, float), np.ones((4, 1))]).ravel()
    return rows


CORNERS = np.array([[100, 100], [200, 100], [200, 140], [100, 140]], float)


def test_an_export_that_matches_the_weights_passes():
    check = compare_frame(onnx_rows((0.9, CORNERS + 0.2), (0.2, CORNERS)), CORNERS[None], np.array([0.9]), 0.4)
    assert check.onnx_count == check.torch_count == 1
    assert check.max_corner_diff_px == pytest.approx(0.2, abs=1e-4) and check.matches


def test_a_missing_detection_or_a_moved_corner_fails():
    assert not compare_frame(onnx_rows(), CORNERS[None], np.array([0.9]), 0.4).matches
    moved = compare_frame(onnx_rows((0.9, CORNERS + MAX_CORNER_DIFF_PX + 1)), CORNERS[None], np.array([0.9]), 0.4)
    assert not moved.matches
