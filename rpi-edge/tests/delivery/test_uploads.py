from datetime import UTC, datetime

import cv2
import numpy as np
import pytest
from fakes import FakeApi, response
from samples import DEVICE_ID, configuration, configuration_document

from common.faults import FaultBoard
from detection.cloud.transport import NetworkError
from detection.config.store import ConfigurationStore
from detection.contract.configuration import PhotosConfiguration
from detection.contract.images import image_key
from detection.delivery.photos import FrameSaver, encode_jpeg
from detection.delivery.queue import PersistentQueue
from detection.delivery.sender import FORBIDDEN_WAIT_SECONDS
from detection.delivery.uploads import DEFERRED_LOG_SECONDS, GATE_RECHECK_SECONDS, IMAGE_CODEC, ImageJob, ImageUploader
from detection.pipeline import FrameResult
from detection.vision.frame import Frame

URL = "https://api.example/api/v1/images/presigned-urls"
CAPTURED = datetime(2026, 11, 13, 4, 5, 6, 789_000, tzinfo=UTC)
FRAMES = ("0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b01", "0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b02")


class FixedConfiguration:
    def __init__(self, low_priority=True):
        self.current = configuration(batching={"imageUrlsBatchSize": 2, "maxBatchDelaySeconds": 10,
                                               "imageUploadsLowPriority": low_priority})


def setup(tmp_path, *answers, frames=FRAMES, link_busy=lambda: False, low_priority=True, clock=lambda: 0.0):
    queue = PersistentQueue(tmp_path / "i.sqlite3", "images", IMAGE_CODEC, 30, 100, lambda: CAPTURED.timestamp())
    jobs = []
    for frame_id in frames:
        path = tmp_path / f"{frame_id}.jpg"
        path.write_bytes(b"jpeg " + frame_id.encode())
        jobs.append(ImageJob(frame_id, CAPTURED, path))
    queue.add(jobs)
    api = FakeApi(*answers)
    uploader = ImageUploader(queue, api, api.http, URL, FixedConfiguration(low_priority), FaultBoard(),
                             link_busy=link_busy,
                             clock=clock)
    return queue, api, uploader, jobs


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


def test_beyond_the_configured_number_of_stored_photos_the_oldest_are_dropped_with_their_files(tmp_path):
    files = []
    store = configured(tmp_path, maxStored=10)
    queue = PersistentQueue(tmp_path / "i.sqlite3", "images", IMAGE_CODEC, 30, 20_000, lambda: CAPTURED.timestamp())
    for n in range(12):
        path = tmp_path / f"f{n}.jpg"
        path.write_bytes(b"x")
        files.append(path)
        queue.add([ImageJob(f"f{n}", CAPTURED, path)])
    api = FakeApi(response(503))
    ImageUploader(queue, api, api.http, URL, store, FaultBoard()).send_once()
    assert queue.pending() == 10 and [p.exists() for p in files[:3]] == [False, False, True]


def test_while_another_stream_uses_the_link_nothing_is_requested_or_uploaded(tmp_path):
    queue, api, uploader, jobs = setup(tmp_path, link_busy=lambda: True)
    assert uploader.send_once() == GATE_RECHECK_SECONDS
    assert api.requests == [] and api.http.uploads == []
    assert queue.pending() == 2 and all(job.path.exists() for job in jobs)


def test_without_the_low_priority_setting_photos_do_not_wait(tmp_path):
    queue, api, uploader, _ = setup(tmp_path, response(200, urls()), link_busy=lambda: True, low_priority=False)
    uploader.send_once()
    assert queue.pending() == 0 and len(api.http.uploads) == 2


def test_a_detection_that_comes_in_between_two_photos_holds_the_second_back(tmp_path):
    queue, api, uploader, jobs = setup(tmp_path, response(200, urls()), response(200, urls()))
    uploader.link_busy = lambda: len(api.http.uploads) == 1  # busy after the first PUT, free again after the pause
    assert uploader.send_once() == GATE_RECHECK_SECONDS
    assert [q.item.frame_id for q in queue.oldest(5)] == [FRAMES[1]] and jobs[1].path.exists()
    uploader.link_busy = lambda: False
    queue.clock = lambda: CAPTURED.timestamp() + 11  # a single photo leaves once it has waited maxBatchDelaySeconds
    uploader.send_once()
    assert queue.pending() == 0 and len(api.requests) == 2  # fresh URLs for the photo that had to wait


def test_a_long_wait_is_reported_once_a_minute_with_the_number_of_photos(tmp_path, capsys):
    now = [0.0]
    _, _, uploader, _ = setup(tmp_path, link_busy=lambda: True, clock=lambda: now[0])
    for second in (0, 2, 4, DEFERRED_LOG_SECONDS + 1):
        now[0] = second
        uploader.send_once()
    out = capsys.readouterr().out
    assert out.count("image_uploads_deferred") == 2 and '"pending": 2' in out


def frame_result(frame_id="f1", events=1):
    return FrameResult(frame_id=frame_id, events=[object()] * events)


def photos_settings(width_px, jpeg_quality):
    return PhotosConfiguration(width_px, jpeg_quality, max_waiting_frames=3, max_stored=2000)


def configured(tmp_path, **photos):
    store = ConfigurationStore(tmp_path / "config")
    store.apply(configuration_document(photos=photos), None)
    return store


def test_the_saver_writes_the_jpeg_atomically_and_queues_the_upload(tmp_path):
    queue = PersistentQueue(tmp_path / "i.sqlite3", "images", IMAGE_CODEC, 30, 100)
    saver = FrameSaver(tmp_path / "frames", queue, configured(tmp_path), encode=lambda frame, photos: b"jpeg bytes")
    frame = Frame(np.zeros((2, 2, 3), np.uint8), CAPTURED)
    saver.save(frame, "f1", photos_settings(4056, 90))
    job = queue.oldest(1)[0].item
    assert job.path.read_bytes() == b"jpeg bytes" and job.frame_id == "f1" and job.captured_at == CAPTURED
    assert not list((tmp_path / "frames").glob("*.part"))


def test_only_frames_with_detections_are_kept_and_a_busy_encoder_drops_photos(tmp_path):
    queue = PersistentQueue(tmp_path / "i.sqlite3", "images", IMAGE_CODEC, 30, 100)
    store = configured(tmp_path, maxWaitingFrames=2)
    saver = FrameSaver(tmp_path / "frames", queue, store, encode=lambda frame, photos: b"x")
    frame = Frame(np.zeros((2, 2, 3), np.uint8), CAPTURED)
    saver.submit(frame, FrameResult())  # nothing detected
    for n in range(4):
        saver.submit(frame, frame_result(f"f{n}"))
    assert saver._waiting.qsize() == 2 and saver.not_saved == 2
    store.apply(configuration_document(photos={"maxWaitingFrames": 3}), None)  # a higher limit applies at once
    saver.submit(frame, frame_result("f4"))
    assert saver._waiting.qsize() == 3 and saver.not_saved == 2


def test_leftovers_of_a_power_cut_are_removed_at_the_start(tmp_path):
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames" / "f1.jpg.part").write_bytes(b"half")
    FrameSaver(tmp_path / "frames", PersistentQueue(tmp_path / "i.sqlite3", "images", IMAGE_CODEC, 30, 100),
               configured(tmp_path))
    assert not list((tmp_path / "frames").glob("*.part"))


def test_a_frame_keeps_the_photo_settings_it_was_analysed_with(tmp_path):
    store = configured(tmp_path, widthPx=2028, jpegQuality=70)
    seen = []
    saver = FrameSaver(tmp_path / "frames", PersistentQueue(tmp_path / "i.sqlite3", "images", IMAGE_CODEC, 30, 100),
                       store, encode=lambda frame, photos: seen.append(photos) or b"x")
    saver.submit(Frame(np.zeros((2, 2, 3), np.uint8), CAPTURED), frame_result("f1"))
    store.apply(configuration_document(photos={"widthPx": 4056}), None)  # a change before the encoder gets to it
    saver.save(*saver._waiting.get_nowait())
    assert seen == [photos_settings(2028, 70)]


def decoded(jpeg: bytes) -> np.ndarray:
    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


def test_a_narrower_setting_downscales_the_photo_keeping_its_aspect_ratio():
    frame = Frame(np.random.default_rng(1).integers(0, 255, (3040, 4056, 3), np.uint8), CAPTURED)
    assert decoded(encode_jpeg(frame, photos_settings(2028, 90))).shape == (1520, 2028, 3)
    assert decoded(encode_jpeg(frame, photos_settings(1000, 90))).shape == (750, 1000, 3)
    assert decoded(encode_jpeg(frame, photos_settings(4056, 90))).shape == (3040, 4056, 3)


def test_a_photo_is_never_upscaled():
    frame = Frame(np.zeros((480, 640, 3), np.uint8), CAPTURED)  # a frame narrower than the setting (replay)
    assert decoded(encode_jpeg(frame, photos_settings(4056, 90))).shape == (480, 640, 3)


def test_a_lower_quality_gives_a_smaller_photo():
    frame = Frame(np.random.default_rng(2).integers(0, 255, (600, 800, 3), np.uint8), CAPTURED)
    assert len(encode_jpeg(frame, photos_settings(800, 50))) < len(encode_jpeg(frame, photos_settings(800, 95)))
