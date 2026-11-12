"""Sends the buffered detections in batches to POST /api/v1/ingest/detections (docs/api/ingest-detections.md).

A batch leaves when batching.detectionsBatchSize detections wait, or when the oldest has waited
batching.maxBatchDelaySeconds. What happens with the answer follows section 4 of the contract:
  2xx                    delete the batch from the outbox
  400, 413, 415          a resend cannot succeed: quarantine the detections the error names (fields[].index),
                         or the whole batch when it names none; the rest is sent again right away
  401                    Api already renewed the token and retried once; back off
  403                    not a device token, a configuration problem: wait long, keep the data
  429, 5xx, no answer    back off exponentially with jitter, resend the same detections (same batchId)
Anything else (404, wrong URL) keeps the data and backs off as well.
"""
import random
import threading
from dataclasses import dataclass

from common.jsonlog import log
from detection.cloud.api import Api
from detection.cloud.cognito import AuthError
from detection.cloud.transport import NetworkError, Response
from detection.config.store import ConfigurationStore
from detection.contract.ingest import DetectionBatch
from detection.contract.problem import Problem
from detection.delivery.outbox import Outbox, QueuedDetection

IDLE_SECONDS = 1.0
BACKOFF_FIRST_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 300.0
FORBIDDEN_WAIT_SECONDS = 600.0
FINAL_STATUSES = (400, 413, 415)
LOGGED_FIELD_ERRORS = 10


@dataclass(frozen=True)
class Batch:
    queued: list[QueuedDetection]  # in the order they are sent, so fields[].index points into it
    pending: int  # detections waiting when the batch was taken, the batch included

    @property
    def request(self) -> DetectionBatch:
        return DetectionBatch(tuple(q.event for q in self.queued))

    @property
    def row_ids(self) -> list[int]:
        return [q.row_id for q in self.queued]


class Sender:
    def __init__(self, outbox: Outbox, api: Api, ingest_url: str, configuration: ConfigurationStore) -> None:
        self.outbox = outbox
        self.api = api
        self.ingest_url = ingest_url
        self.configuration = configuration
        self.failures = 0  # consecutive failed attempts, for the backoff

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                wait = self.send_once()
            except Exception as e:  # never let the sender thread die
                log("sender_error", level="error", error=repr(e))
                wait = self._backoff()
            stop.wait(wait)

    def send_once(self) -> float:
        """One step: maybe one request. Returns the seconds to wait before the next step."""
        dropped = self.outbox.prune()
        if dropped:
            log("detections_dropped", level="warning", count=dropped, reason="retention")
        batch, wait = self._next_batch()
        if batch is None:
            return wait
        request = batch.request
        try:
            response = self.api.request("POST", self.ingest_url, trace_id=request.batch_id,
                                        body=request.to_document(), headers={"Content-Type": "application/json"})
        except (NetworkError, AuthError) as e:
            log("batch_not_sent", level="warning", traceId=request.batch_id, count=len(batch.queued), error=str(e))
            return self._backoff()
        return self._handle(response, batch)

    def _next_batch(self) -> tuple[Batch | None, float]:
        """A batch to send now, or None and how long to wait for one."""
        configuration = self.configuration.current
        pending = self.outbox.pending()
        if configuration is None or pending == 0:
            return None, IDLE_SECONDS
        size, max_delay = configuration.batching.detections_batch_size, configuration.batching.max_batch_delay_seconds
        age = self.outbox.oldest_age_seconds()
        if pending < size and age < max_delay:
            return None, min(IDLE_SECONDS, max_delay - age)
        return Batch(self.outbox.oldest(size), pending), 0.0

    def _handle(self, response: Response, batch: Batch) -> float:
        status, trace_id, count = response.status, batch.request.batch_id, len(batch.queued)
        if 200 <= status < 300:
            self.outbox.delete(batch.row_ids)
            self.failures = 0
            left = batch.pending - count
            log("batch_sent", traceId=trace_id, count=count, status=status, pending=left)
            return 0.0 if left >= self.configuration.current.batching.detections_batch_size else IDLE_SECONDS
        if status in FINAL_STATUSES:
            self._quarantine(batch, Problem.of(status, response.body))
            return 0.0  # the rest of the batch goes again right away
        if status == 403:
            log("batch_forbidden", level="error", traceId=trace_id, count=count,
                hint="the token is not a device token: check COGNITO_CLIENT_ID and the device account")
            return FORBIDDEN_WAIT_SECONDS
        log("batch_failed", level="warning", traceId=trace_id, count=count, status=status)
        return max(self._backoff(), _retry_after(response.headers) or 0.0)

    def _quarantine(self, batch: Batch, problem: Problem) -> None:
        named = problem.indexes
        bad = [q.row_id for i, q in enumerate(batch.queued) if i in named] or batch.row_ids
        code = problem.code or f"HTTP {problem.status}"
        self.outbox.quarantine(bad, problem.status, code)
        log("detections_quarantined", level="error", traceId=batch.request.batch_id, count=len(bad),
            status=problem.status, code=code,
            fields=[{"index": f.index, "field": f.field, "code": f.code} for f in problem.fields][:LOGGED_FIELD_ERRORS])

    def _backoff(self) -> float:
        """Exponential backoff; the jitter spreads retries of many devices after a shared outage."""
        self.failures += 1
        delay = min(BACKOFF_MAX_SECONDS, BACKOFF_FIRST_SECONDS * 2 ** (self.failures - 1))
        return delay / 2 + random.uniform(0, delay / 2)


def _retry_after(headers: dict) -> float | None:
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None
