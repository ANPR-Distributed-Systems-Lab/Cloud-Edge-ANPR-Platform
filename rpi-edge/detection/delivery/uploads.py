"""Uploads the photos of the frames of detections to S3 (docs/api/ingest-detections.md, section 7).

A detection leaves with the S3 key of its photo (contract/images.py) as soon as it is accepted; the photo follows from
here, independently: frames wait as files on the SD card with a row in the `images` queue, and in batches the
uploader asks device-management for presigned PUT URLs (POST /api/v1/images/presigned-urls) and PUTs each file.

  presigned-urls   2xx: upload every file of the batch; the key the platform returns must be the key the device
                   computed (the detection already carries it), otherwise the photo is quarantined
                   400, 413, 415: quarantine the frames the error names (fields[].index), or the whole batch
                   403: wait long; 429, 5xx, no answer, anything else: back off and ask again
  PUT              a refused or failed upload keeps the file and the row; the next attempt asks for fresh URLs,
                   which also covers an expired URL

Files are deleted with their rows (uploaded, quarantined or past the retention).

Fault (common/fault_catalog.py) photos not sent: error answers in a row for the URLs or the PUTs (an invalid answer
counts too) that no fault of the account explains, cleared by the next uploaded batch. Photos dropped by the
retention or photos.maxStored are a limit set on purpose: logged, no fault.

Priority (batching.imageUploadsLowPriority, on by default): a photo is the largest thing the device sends and a
PUT cannot be paused, so photos give way to everything else. While another stream (detections, locations, metrics)
has something to send or a request in flight, the uploader neither asks for URLs nor starts a PUT, and looks again
every GATE_RECHECK_SECONDS. The photos wait in the queue and go out in the pauses; a PUT that has started finishes.
"""
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from common import fault_catalog as kinds
from common.faults import FaultBoard
from common.jsonlog import log
from detection.cloud.api import Api, account_fault
from detection.cloud.cognito import AuthError
from detection.cloud.transport import Http, NetworkError, Response
from detection.config.store import ConfigurationStore
from detection.contract.images import CONTENT_TYPE, FrameToUpload, ImageUploadRequest, ImageUploadUrls, image_key
from detection.contract.parsing import ContractError
from detection.contract.problem import Problem
from detection.contract.wire import iso_ms, parse_iso_ms
from detection.delivery.answers import Outcome, outcome_of, retry_after
from detection.delivery.backoff import Backoff
from detection.delivery.queue import Batch, ItemCodec, PersistentQueue, Queued
from detection.delivery.sender import (
    BACKOFF_FIRST_SECONDS,
    BACKOFF_MAX_SECONDS,
    FORBIDDEN_WAIT_SECONDS,
    IDLE_SECONDS,
    LOGGED_FIELD_ERRORS,
)


@dataclass(frozen=True)
class ImageJob:
    """A photo waiting to be uploaded: the frame it shows and where the JPEG is."""
    frame_id: str
    captured_at: datetime
    path: Path

    def to_document(self) -> dict:
        return {"frameId": self.frame_id, "capturedAt": iso_ms(self.captured_at), "path": str(self.path)}

    @classmethod
    def from_document(cls, document: dict) -> "ImageJob":
        return cls(document["frameId"], parse_iso_ms(document["capturedAt"]), Path(document["path"]))


IMAGE_CODEC = ItemCodec(ImageJob.to_document, ImageJob.from_document, lambda j: j.frame_id,
                        lambda j: j.captured_at.timestamp())


GATE_RECHECK_SECONDS = 2.0  # how often a photo that gives way looks at the link again
DEFERRED_LOG_SECONDS = 60.0  # how often a long wait is reported


class ImageUploader:
    def __init__(self, queue: PersistentQueue[ImageJob], api: Api, http: Http, url: str,
                 configuration: ConfigurationStore, faults: FaultBoard, link_busy: Callable[[], bool] = lambda: False,
                 clock: Callable[[], float] = time.monotonic) -> None:
        """`link_busy` tells whether any other stream is using the link (Sender.is_active of each of them)."""
        self.queue = queue
        self.api = api
        self.http = http
        self.url = url
        self.configuration = configuration
        self.faults = faults
        self.link_busy = link_busy
        self.clock = clock
        self.backoff = Backoff(BACKOFF_FIRST_SECONDS, BACKOFF_MAX_SECONDS)
        self._deferred_logged_at: float | None = None

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                wait = self.send_once()
            except Exception as e:  # never let the uploader thread die
                log("uploader_error", level="error", error=repr(e))
                wait = self.backoff.next_delay()
            stop.wait(wait)

    def send_once(self) -> float:
        """One step: maybe one request for URLs and the uploads that follow. Returns the seconds to wait."""
        configuration = self.configuration.current
        dropped = self.queue.prune(configuration.photos.max_stored if configuration else None)
        for job in dropped:
            job.path.unlink(missing_ok=True)
        if dropped:
            log("items_dropped", level="warning", stream="images", count=len(dropped),
                reason="retention or photos.maxStored")
        if configuration is None:
            return IDLE_SECONDS
        low_priority = configuration.batching.image_uploads_low_priority
        if low_priority and self.link_busy():
            return self._defer()
        batch, wait = self.queue.take_due(configuration.batching.image_urls_batch_size,
                                          configuration.batching.max_batch_delay_seconds)
        if batch is None:
            return min(wait, IDLE_SECONDS) if wait > 0 else IDLE_SECONDS
        self._deferred_logged_at = None
        request = ImageUploadRequest(tuple(FrameToUpload(j.frame_id, j.captured_at) for j in batch.items))
        try:
            response = self.api.request("POST", self.url, trace_id=request.trace_id, body=request.to_document(),
                                        headers={"Content-Type": "application/json"})
        except (NetworkError, AuthError) as e:
            log("image_urls_not_requested", level="warning", traceId=request.trace_id, error=str(e))
            return self.backoff.next_delay()
        return self._handle(response, batch, request.trace_id, configuration.device_id, low_priority)

    def _defer(self) -> float:
        """Gives way to the other streams; reports a long wait now and then, with how many photos are waiting."""
        now = self.clock()
        if self.queue.pending() and (self._deferred_logged_at is None
                                     or now - self._deferred_logged_at >= DEFERRED_LOG_SECONDS):
            self._deferred_logged_at = now
            log("image_uploads_deferred", pending=self.queue.pending(), reason="other streams are using the link")
        return GATE_RECHECK_SECONDS

    def _handle(self, response: Response, batch: Batch[ImageJob], trace_id: str, device_id: str,
                low_priority: bool) -> float:
        outcome = outcome_of(response.status)
        if outcome is Outcome.ACCEPTED:
            return self._upload(response, batch, trace_id, device_id, low_priority)
        if outcome is Outcome.REFUSED:
            problem = Problem.of(response.status, response.body)
            bad = [q for i, q in enumerate(batch.queued) if i in problem.indexes] or list(batch.queued)
            self._quarantine(bad, problem.status, problem.code or f"HTTP {problem.status}")
            log("images_quarantined", level="error", traceId=trace_id, count=len(bad), status=problem.status,
                code=problem.code, fields=[{"index": f.index, "field": f.field, "code": f.code}
                                           for f in problem.fields][:LOGGED_FIELD_ERRORS])
            return 0.0
        if outcome is Outcome.FORBIDDEN:
            log("image_urls_forbidden", level="error", traceId=trace_id, hint="check the device account")
            return FORBIDDEN_WAIT_SECONDS
        if account_fault(response) is None:
            self.faults.failed(kinds.PHOTOS_NOT_SENT)
        log("image_urls_failed", level="warning", traceId=trace_id, status=response.status)
        return max(self.backoff.next_delay(), retry_after(response.headers) or 0.0)

    def _upload(self, response: Response, batch: Batch[ImageJob], trace_id: str, device_id: str,
                low_priority: bool) -> float:
        try:
            urls = ImageUploadUrls.from_document(response.json())
        except (ContractError, ValueError) as e:
            self.faults.failed(kinds.PHOTOS_NOT_SENT)
            log("image_urls_invalid", level="error", traceId=trace_id,
                problems=e.problems if isinstance(e, ContractError) else [str(e)])
            return self.backoff.next_delay()
        for queued in batch.queued:
            job = queued.item
            problem = self._unusable(job, urls, device_id)
            if problem:
                log("image_quarantined", level="error", traceId=trace_id, frameId=job.frame_id, reason=problem)
                self._quarantine([queued], response.status, problem)
                continue
            if low_priority and self.link_busy():  # a detection came in meanwhile: the rest waits, URLs are cheap
                return self._defer()
            try:
                status = self.http.upload(urls.for_frame(job.frame_id).upload_url, job.path, CONTENT_TYPE)
            except NetworkError as e:
                log("image_not_uploaded", level="warning", traceId=trace_id, frameId=job.frame_id, error=str(e))
                return self.backoff.next_delay()
            if outcome_of(status) is not Outcome.ACCEPTED:
                self.faults.failed(kinds.PHOTOS_NOT_SENT)
                log("image_not_uploaded", level="warning", traceId=trace_id, frameId=job.frame_id, status=status)
                return self.backoff.next_delay()
            self.queue.delete([queued.row_id])
            job.path.unlink(missing_ok=True)
        self.backoff.reset()
        self.faults.succeeded(kinds.PHOTOS_NOT_SENT)
        log("images_uploaded", traceId=trace_id, count=len(batch.queued), pending=self.queue.pending())
        return 0.0 if self.queue.pending() else IDLE_SECONDS

    @staticmethod
    def _unusable(job: ImageJob, urls: ImageUploadUrls, device_id: str) -> str | None:
        """Why the photo cannot be uploaded, or None."""
        upload = urls.for_frame(job.frame_id)
        if upload is None:
            return "NO_URL_FOR_FRAME"
        if upload.image_key != image_key(device_id, job.frame_id, job.captured_at):
            return "IMAGE_KEY_MISMATCH"  # the detection carries the key the device computed
        if not job.path.is_file():
            return "FILE_MISSING"
        return None

    def _quarantine(self, queued: list[Queued[ImageJob]], status: int, reason: str) -> None:
        self.queue.quarantine([q.row_id for q in queued], status, reason)
        for q in queued:
            q.item.path.unlink(missing_ok=True)
