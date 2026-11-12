"""Sends the buffered detections in batches to POST /api/v1/ingest/detections (docs/api/ingest-detections.md).

A batch leaves when detectionsBatchSize detections wait, or when the oldest has waited maxBatchDelaySeconds.
What happens with the answer follows section 4 of the contract:
  202                    delete the batch from the outbox
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
from detection.config.settings import Settings
from detection.delivery.events import batch_id
from detection.delivery.outbox import Outbox

IDLE_SECONDS = 1.0
BACKOFF_FIRST_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 300.0
FORBIDDEN_WAIT_SECONDS = 600.0
FINAL_STATUSES = (400, 413, 415)
LOGGED_FIELD_ERRORS = 10


@dataclass
class Batch:
    row_ids: list[int]  # outbox rows, in the order of `detections`
    detections: list[dict]
    pending: int  # detections waiting when the batch was taken, the batch included

    @property
    def batch_id(self) -> str:
        return batch_id([d["detectionId"] for d in self.detections])


class Sender:
    def __init__(self, outbox: Outbox, api: Api, ingest_url: str, settings: Settings) -> None:
        self.outbox = outbox
        self.api = api
        self.ingest_url = ingest_url
        self.settings = settings
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
        trace_id = batch.batch_id
        try:
            response = self.api.request("POST", self.ingest_url, trace_id=trace_id,
                                        body={"batchId": trace_id, "detections": batch.detections},
                                        headers={"Content-Type": "application/json"})
        except (NetworkError, AuthError) as e:
            log("batch_not_sent", level="warning", traceId=trace_id, count=len(batch.row_ids), error=str(e))
            return self._backoff()
        return self._handle(response, batch)

    def _next_batch(self) -> tuple[Batch | None, float]:
        """A batch to send now, or None and how long to wait for one."""
        batching = self.settings.current.batching
        size, max_delay = batching.detections_batch_size, batching.max_batch_delay_seconds
        pending, age = self.outbox.pending(), self.outbox.oldest_age_seconds()
        if pending == 0:
            return None, IDLE_SECONDS
        if pending < size and age < max_delay:
            return None, min(IDLE_SECONDS, max_delay - age)
        rows = self.outbox.oldest(size)
        return Batch([row_id for row_id, _ in rows], [body for _, body in rows], pending), 0.0

    def _handle(self, response: Response, batch: Batch) -> float:
        status, trace_id, count = response.status, batch.batch_id, len(batch.row_ids)
        if 200 <= status < 300:
            self.outbox.delete(batch.row_ids)
            self.failures = 0
            left = batch.pending - count
            log("batch_sent", traceId=trace_id, count=count, status=status, pending=left)
            return 0.0 if left >= self.settings.current.batching.detections_batch_size else IDLE_SECONDS
        if status in FINAL_STATUSES:
            self._quarantine(batch, response)
            return 0.0  # the rest of the batch goes again right away
        if status == 403:
            log("batch_forbidden", level="error", traceId=trace_id, count=count,
                hint="the token is not a device token: check COGNITO_CLIENT_ID and the device account")
            return FORBIDDEN_WAIT_SECONDS
        log("batch_failed", level="warning", traceId=trace_id, count=count, status=status)
        return max(self._backoff(), _retry_after(response.headers) or 0.0)

    def _quarantine(self, batch: Batch, response: Response) -> None:
        problem = _problem(response)
        field_errors = [f for f in problem.get("fields") or [] if isinstance(f, dict)]
        named = {f["index"] for f in field_errors if isinstance(f.get("index"), int)}
        bad = [row_id for i, row_id in enumerate(batch.row_ids) if i in named] or batch.row_ids
        code = str(problem.get("code") or f"HTTP {response.status}")
        self.outbox.quarantine(bad, response.status, code)
        # The field codes name the rule broken, never the value, so they are safe to log.
        log("detections_quarantined", level="error", traceId=batch.batch_id, count=len(bad), status=response.status,
            code=code, fields=[{k: f.get(k) for k in ("index", "field", "code")}
                               for f in field_errors][:LOGGED_FIELD_ERRORS])

    def _backoff(self) -> float:
        """Exponential backoff; the jitter spreads retries of many devices after a shared outage."""
        self.failures += 1
        delay = min(BACKOFF_MAX_SECONDS, BACKOFF_FIRST_SECONDS * 2 ** (self.failures - 1))
        return delay / 2 + random.uniform(0, delay / 2)


def _problem(response: Response) -> dict:
    """The RFC 9457 problem document of an error response, or {} when there is none."""
    try:
        problem = response.json()
    except ValueError:
        return {}
    return problem if isinstance(problem, dict) else {}


def _retry_after(headers: dict) -> float | None:
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return None
