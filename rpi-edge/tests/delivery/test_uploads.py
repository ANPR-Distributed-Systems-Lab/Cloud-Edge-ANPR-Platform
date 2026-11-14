from datetime import UTC, datetime

import numpy as np
import pytest
from fakes import FakeApi, response
from samples import DEVICE_ID, configuration

from detection.cloud.transport import NetworkError
from detection.contract.images import image_key
from detection.delivery.photos import MAX_WAITING_FRAMES, FrameSaver
from detection.delivery.queue import PersistentQueue
from detection.delivery.sender import FORBIDDEN_WAIT_SECONDS
from detection.delivery.uploads import IMAGE_CODEC, ImageJob, ImageUploader
from detection.pipeline import FrameResult
from detection.vision.frame import Frame

URL = "https://api.example/api/v1/images/presigned-urls"
CAPTURED = datetime(2026, 11, 13, 4, 5, 6, 789_000, tzinfo=UTC)
FRAMES = ("0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b01", "0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b02")


class FixedConfiguration:
    current = configuration(batching={"imageUrlsBatchSize": 2, "maxBatchDelaySeconds": 10})


def setup(tmp_path, *answers, frames=FRAMES):
    queue = PersistentQueue(tmp_path / "i.sqlite3", "images", IMAGE_CODEC, 30, 100, lambda: CAPTURED.timestamp())
    jobs = []
    for frame_id in frames:
        path = tmp_path / f"{frame_id}.jpg"
        path.write_bytes(b"jpeg " + frame_id.encode())
        jobs.append(ImageJob(frame_id, CAPTURED, path))
    queue.add(jobs)
    api = FakeApi(*answers)
    return queue, api, ImageUploader(queue, api, api.http, URL, FixedConfiguration()), jobs


def urls(frames=FRAMES, **override):
    return {"uploads": [{"frameId": f, "imageKey": image_key(DEVICE_ID, f, CAPTURED),
                         "uploadUrl": f"https://s3.example/{f}?X-Amz-Signature=s", "expiresAt": "2026-11-13T04:35:06Z"}
                        | override for f in frames]}


def test_a_batch_asks_for_urls_uploads_every_photo_and_deletes_files_and_rows(tmp_path):
    queue, api, uploader, jobs = setup(tmp_path, response(200, urls()))
    uploader.send_once()
    [request] = api.requests
    assert request["url"] == URL
    assert request["body"] == {"frames": [{"frameId": f, "capturedAt": "2026-11-13T04:05:06.789Z"} for f in FRAMES]}
    assert [u["url"].split("?")[0].rsplit("/", 1)[1] for u in api.http.uploads] == list(FRAMES)
    assert all(u["content_type"] == "image/jpeg" and u["bytes"].startswith(b"jpeg ") for u in api.http.uploads)
    assert queue.pending() == 0 and not any(job.path.exists() for job in jobs)


def test_a_failed_upload_keeps_the_rest_and_asks_for_fresh_urls_next_time(tmp_path):
    queue, api, uploader, jobs = setup(tmp_path, response(200, urls()), response(200, urls()))
    api.http.upload_answers = [403]  # an expired URL
    assert uploader.send_once() >= 1.0
    assert queue.pending() == 2 and all(job.path.exists() for job in jobs)
    uploader.send_once()
    assert queue.pending() == 0 and len(api.requests) == 2


def test_a_network_error_during_an_upload_keeps_the_photo(tmp_path):
    queue, api, uploader, jobs = setup(tmp_path, response(200, urls()))
    api.http.upload_answers = [200, NetworkError("offline")]
    uploader.send_once()
    assert [q.item.frame_id for q in queue.oldest(5)] == [FRAMES[1]] and jobs[1].path.exists()


def test_a_key_other_than_the_one_in_the_detections_is_never_uploaded(tmp_path):
    answer = urls()
    answer["uploads"][1]["imageKey"] = image_key(DEVICE_ID, "0192f3a4-7c1e-7000-b5c3-1d2e3f4a5bff", CAPTURED)
    queue, api, uploader, jobs = setup(tmp_path, response(200, answer))
    uploader.send_once()
    assert [u["url"].split("?")[0].rsplit("/", 1)[1] for u in api.http.uploads] == [FRAMES[0]]
    assert queue.quarantined() == 1 and queue.pending() == 0 and not jobs[1].path.exists()


def test_a_missing_file_is_quarantined(tmp_path):
    queue, api, uploader, jobs = setup(tmp_path, response(200, urls()))
    jobs[0].path.unlink()
    uploader.send_once()
    assert queue.quarantined() == 1 and len(api.http.uploads) == 1


def test_a_400_quarantines_the_frames_it_names_and_deletes_their_files(tmp_path):
    problem = {"code": "VALIDATION_FAILED", "fields": [
        {"index": 0, "field": "frames[0].capturedAt", "code": "TIMESTAMP_TOO_OLD"}]}
    queue, api, uploader, jobs = setup(tmp_path, response(400, problem))
    assert uploader.send_once() == 0.0
    assert queue.quarantined() == 1 and queue.pending() == 1
    assert not jobs[0].path.exists() and jobs[1].path.exists() and api.http.uploads == []


@pytest.mark.parametrize("answer, minimum", [(response(503), 1.0), (NetworkError("offline"), 1.0),
                                              (response(403, {"code": "FORBIDDEN"}), FORBIDDEN_WAIT_SECONDS)])
def test_failures_keep_everything_and_wait(tmp_path, answer, minimum):
    queue, api, uploader, jobs = setup(tmp_path, answer)
    assert uploader.send_once() >= minimum
    assert queue.pending() == 2 and all(job.path.exists() for job in jobs)


def test_an_invalid_answer_keeps_everything(tmp_path):
    queue, api, uploader, jobs = setup(tmp_path, response(200, {"uploads": []}))
    uploader.send_once()
    assert queue.pending() == 2 and api.http.uploads == []


def test_photos_past_the_retention_are_dropped_with_their_files(tmp_path):
    queue, api, uploader, jobs = setup(tmp_path)
    queue.retention_seconds = -1
    uploader.send_once()
    assert queue.pending() == 0 and not any(job.path.exists() for job in jobs)


def frame_result(frame_id="f1", events=1):
    return FrameResult(frame_id=frame_id, events=[object()] * events)


def test_the_saver_writes_the_jpeg_atomically_and_queues_the_upload(tmp_path):
    queue = PersistentQueue(tmp_path / "i.sqlite3", "images", IMAGE_CODEC, 30, 100)
    saver = FrameSaver(tmp_path / "frames", queue, encode=lambda frame: b"jpeg bytes")
    frame = Frame(np.zeros((2, 2, 3), np.uint8), CAPTURED)
    saver.save(frame, "f1")
    job = queue.oldest(1)[0].item
    assert job.path.read_bytes() == b"jpeg bytes" and job.frame_id == "f1" and job.captured_at == CAPTURED
    assert not list((tmp_path / "frames").glob("*.part"))


def test_only_frames_with_detections_are_kept_and_a_busy_encoder_drops_photos(tmp_path):
    queue = PersistentQueue(tmp_path / "i.sqlite3", "images", IMAGE_CODEC, 30, 100)
    saver = FrameSaver(tmp_path / "frames", queue, encode=lambda frame: b"x")
    frame = Frame(np.zeros((2, 2, 3), np.uint8), CAPTURED)
    saver.submit(frame, FrameResult())  # nothing detected
    for n in range(MAX_WAITING_FRAMES + 2):
        saver.submit(frame, frame_result(f"f{n}"))
    assert saver._waiting.qsize() == MAX_WAITING_FRAMES and saver.not_saved == 2


def test_leftovers_of_a_power_cut_are_removed_at_the_start(tmp_path):
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames" / "f1.jpg.part").write_bytes(b"half")
    FrameSaver(tmp_path / "frames", PersistentQueue(tmp_path / "i.sqlite3", "images", IMAGE_CODEC, 30, 100))
    assert not list((tmp_path / "frames").glob("*.part"))
