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
"""
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from common.jsonlog import log
from detection.cloud.api import Api
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
from detection.delivery.sender import BACKOFF_FIRST_SECONDS, BACKOFF_MAX_SECONDS, FORBIDDEN_WAIT_SECONDS, IDLE_SECONDS


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


class ImageUploader:
    def __init__(self, queue: PersistentQueue[ImageJob], api: Api, http: Http, url: str,
                 configuration: ConfigurationStore) -> None:
        self.queue = queue
        self.api = api
        self.http = http
        self.url = url
        self.configuration = configuration
        self.backoff = Backoff(BACKOFF_FIRST_SECONDS, BACKOFF_MAX_SECONDS)

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
        dropped = self.queue.prune()
        for job in dropped:
            job.path.unlink(missing_ok=True)
        if dropped:
            log("items_dropped", level="warning", stream="images", count=len(dropped), reason="retention")
        configuration = self.configuration.current
        if configuration is None:
            return IDLE_SECONDS
        batch, wait = self.queue.take_due(configuration.batching.image_urls_batch_size,
                                          configuration.batching.max_batch_delay_seconds)
        if batch is None:
            return min(wait, IDLE_SECONDS) if wait > 0 else IDLE_SECONDS
        request = ImageUploadRequest(tuple(FrameToUpload(j.frame_id, j.captured_at) for j in batch.items))
        try:
            response = self.api.request("POST", self.url, trace_id=request.trace_id, body=request.to_document(),
                                        headers={"Content-Type": "application/json"})
        except (NetworkError, AuthError) as e:
            log("image_urls_not_requested", level="warning", traceId=request.trace_id, error=str(e))
            return self.backoff.next_delay()
        return self._handle(response, batch, request.trace_id, configuration.device_id)

    def _handle(self, response: Response, batch: Batch[ImageJob], trace_id: str, device_id: str) -> float:
        outcome = outcome_of(response.status)
        if outcome is Outcome.ACCEPTED:
            return self._upload(response, batch, trace_id, device_id)
        if outcome is Outcome.REFUSED:
            problem = Problem.of(response.status, response.body)
            bad = [q for i, q in enumerate(batch.queued) if i in problem.indexes] or list(batch.queued)
            self._quarantine(bad, problem.status, problem.code or f"HTTP {problem.status}")
            log("images_quarantined", level="error", traceId=trace_id, count=len(bad), status=problem.status,
                code=problem.code, fields=[{"index": f.index, "field": f.field, "code": f.code}
                                           for f in problem.fields][:10])
            return 0.0
        if outcome is Outcome.FORBIDDEN:
            log("image_urls_forbidden", level="error", traceId=trace_id, hint="check the device account")
            return FORBIDDEN_WAIT_SECONDS
        log("image_urls_failed", level="warning", traceId=trace_id, status=response.status)
        return max(self.backoff.next_delay(), retry_after(response.headers) or 0.0)

    def _upload(self, response: Response, batch: Batch[ImageJob], trace_id: str, device_id: str) -> float:
        try:
            urls = ImageUploadUrls.from_document(response.json())
        except (ContractError, ValueError) as e:
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
            try:
                status = self.http.upload(urls.for_frame(job.frame_id).upload_url, job.path, CONTENT_TYPE)
            except NetworkError as e:
                log("image_not_uploaded", level="warning", traceId=trace_id, frameId=job.frame_id, error=str(e))
                return self.backoff.next_delay()
            if outcome_of(status) is not Outcome.ACCEPTED:
                log("image_not_uploaded", level="warning", traceId=trace_id, frameId=job.frame_id, status=status)
                return self.backoff.next_delay()
            self.queue.delete([queued.row_id])
            job.path.unlink(missing_ok=True)
        self.backoff.reset()
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
