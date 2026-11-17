from datetime import UTC, datetime

import pytest
from samples import DEVICE_ID

from detection.contract.images import FrameToUpload, ImageUploadRequest, ImageUploadUrls, image_key
from detection.contract.parsing import ContractError

FRAME_ID = "0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c"
CAPTURED = datetime(2026, 10, 30, 23, 59, 59, 500_000, tzinfo=UTC)
KEY = f"images/{DEVICE_ID}/2026/10/30/{FRAME_ID}.jpg"


def upload(**override):
    return {"frameId": FRAME_ID, "imageKey": KEY, "uploadUrl": "https://s3.example/x?X-Amz-Signature=s",
            "expiresAt": "2026-10-31T00:30:00Z"} | override


def test_the_key_follows_the_contract_with_the_utc_date_of_the_capture():
    assert image_key(DEVICE_ID, FRAME_ID, CAPTURED) == KEY
    local = datetime.fromisoformat("2026-10-31T01:59:59+02:00")  # the same instant as 23:59:59Z
    assert image_key(DEVICE_ID, FRAME_ID, local) == KEY


def test_the_request_lists_the_frames():
    request = ImageUploadRequest((FrameToUpload(FRAME_ID, CAPTURED),))
    assert request.to_document() == {"frames": [{"frameId": FRAME_ID, "capturedAt": "2026-10-30T23:59:59.500Z"}]}
    assert request.trace_id == ImageUploadRequest((FrameToUpload(FRAME_ID, CAPTURED),)).trace_id


def test_the_answer_maps_onto_uploads_found_by_frame():
    urls = ImageUploadUrls.from_document({"uploads": [upload()]})
    assert urls.for_frame(FRAME_ID).image_key == KEY
    assert urls.for_frame("0192f3a4-7c1e-7000-b5c3-000000000000") is None


@pytest.mark.parametrize("override, problem", [
    ({"imageKey": "photos/a.jpg"}, "uploads[0].imageKey must match"),
    ({"frameId": "x"}, "uploads[0].frameId must match"),
    ({"uploadUrl": ""}, "uploads[0].uploadUrl must match"),
])
def test_answers_outside_the_contract_are_named(override, problem):
    with pytest.raises(ContractError) as e:
        ImageUploadUrls.from_document({"uploads": [upload(**override)]})
    assert any(p.startswith(problem) for p in e.value.problems)
