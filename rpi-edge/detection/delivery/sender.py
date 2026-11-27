"""Sends the buffered items of one stream in batches (detections, device locations, device metrics).

A batch leaves when the stream's batch size of items wait, or when the oldest has waited the stream's maximum delay.
What happens with the answer follows section 4 of the ingest contract (docs/api/ingest-detections.md), which the
device-management endpoints share:
  2xx                    delete the batch from the queue
  400, 413, 415          a resend cannot succeed: quarantine the items the error names (fields[].index),
                         or the whole batch when it names none; the rest is sent again right away
  401                    Api already renewed the token and retried once; back off
  403                    not a device token, a configuration problem: wait long, keep the data
  429, 5xx, no answer    back off exponentially with jitter, resend the same items (same batch id)
Anything else (404, wrong URL) keeps the data and backs off as well (delivery/answers.py).

Faults (common/fault_catalog.py): the stream's own (plates / track / metrics not sent) after error answers in a row
that no fault of the account explains (cloud/api.py), cleared by the next accepted batch; data dropped when the
retention deletes items of a stream whose loss counts (plates, track). A refused batch counts in the quarantine
(feedback/faults.py), no answer at all only on the network LED.
"""
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from common import fault_catalog as kinds
from common.faults import FaultBoard, FaultKind
from common.jsonlog import log
from detection.cloud.api import Api, account_fault
from detection.cloud.cognito import AuthError
from detection.cloud.transport import NetworkError, Response
from detection.config.store import ConfigurationStore
from detection.contract.configuration import DeviceConfiguration
from detection.contract.problem import Problem
from detection.contract.wire import Request
from detection.delivery.answers import Outcome, outcome_of, retry_after
from detection.delivery.backoff import Backoff
from detection.delivery.queue import Batch, PersistentQueue

IDLE_SECONDS = 1.0  # how often a sender with nothing due looks at its queue again
BACKOFF_FIRST_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 300.0
FORBIDDEN_WAIT_SECONDS = 600.0  # a 403 needs a fix of the setup, not a quick retry
LOGGED_FIELD_ERRORS = 10  # field errors in one log line at most: a refused batch of 100 must not flood the log


@dataclass(frozen=True)
class Stream[T]:
    """One kind of item and where it goes."""
    name: str  # in the logs: detections, locations, metrics
    url: str
    queue: PersistentQueue[T]
    request: Callable[[tuple[T, ...]], Request]  # the body and the trace id of a batch
    batch_size: Callable[[DeviceConfiguration], int]
    max_delay_seconds: Callable[[DeviceConfiguration], float]
    fault: FaultKind  # lit while the platform keeps answering this stream with errors
    loss_is_fault: bool  # items dropped by the retention are a fault (data dropped)


class Sender[T]:
    def __init__(self, stream: Stream[T], api: Api, configuration: ConfigurationStore, faults: FaultBoard,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.stream = stream
        self.api = api
        self.configuration = configuration
        self.faults = faults
        self.clock = clock
        self.backoff = Backoff(BACKOFF_FIRST_SECONDS, BACKOFF_MAX_SECONDS)
        self._in_flight = False  # a request of this stream is on the link
        self._resting_until = 0.0  # after a failure the stream waits and does not use the link

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                wait = self.send_once()
            except Exception as e:  # never let the sender thread die
                log("sender_error", level="error", stream=self.stream.name, error=repr(e))
                wait = self.backoff.next_delay()
            stop.wait(wait)

    def is_active(self) -> bool:
        """Whether this stream uses the link or is about to: a request in flight, or items waiting to be sent (also
        for their batch to be due). A stream that rests after a failure does not count, so an endpoint that keeps
        failing never keeps the photos from going out."""
        if self._in_flight:
            return True
        return self.stream.queue.pending() > 0 and self.clock() >= self._resting_until

    def send_once(self) -> float:
        """One step: maybe one request. Returns the seconds to wait before the next step."""
        queue = self.stream.queue
        dropped = queue.prune()
        if dropped:
            log("items_dropped", level="warning", stream=self.stream.name, count=len(dropped), reason="retention")
            if self.stream.loss_is_fault:
                self.faults.add(kinds.DATA_DROPPED, len(dropped))
        batch, wait = self._next_batch()
        if batch is None:
            return wait
        request = self.stream.request(batch.items)
        self._in_flight = True
        try:
            response = self.api.request("POST", self.stream.url, trace_id=request.trace_id,
                                        body=request.to_document(), headers={"Content-Type": "application/json"})
        except (NetworkError, AuthError) as e:
            log("batch_not_sent", level="warning", stream=self.stream.name, traceId=request.trace_id,
                count=len(batch.queued), error=str(e))
            return self._rest(self.backoff.next_delay())
        finally:
            self._in_flight = False
        return self._handle(response, batch, request.trace_id)

    def _rest(self, seconds: float) -> float:
        """Waits `seconds` after a failure, without counting as a user of the link."""
        self._resting_until = self.clock() + seconds
        return seconds

    def _next_batch(self) -> tuple[Batch[T] | None, float]:
        """A batch to send now, or None and how long to wait for one."""
        configuration = self.configuration.current
        if configuration is None:
            return None, IDLE_SECONDS
        batch, wait = self.stream.queue.take_due(self.stream.batch_size(configuration),
                                                 self.stream.max_delay_seconds(configuration))
        if batch is not None:
            return batch, 0.0
        return None, min(wait, IDLE_SECONDS) if wait > 0 else IDLE_SECONDS

    def _handle(self, response: Response, batch: Batch[T], trace_id: str) -> float:
        status, count = response.status, len(batch.queued)
        outcome = outcome_of(status)
        if outcome is Outcome.ACCEPTED:
            self.faults.succeeded(self.stream.fault)
            self.stream.queue.delete(batch.row_ids)
            self.backoff.reset()
            self._resting_until = 0.0
            left = batch.pending - count
            log("batch_sent", stream=self.stream.name, traceId=trace_id, count=count, status=status, pending=left)
            full_batch = self.stream.batch_size(self.configuration.current)
            return 0.0 if left >= full_batch else IDLE_SECONDS
        if outcome is Outcome.REFUSED:
            self._quarantine(batch, Problem.of(status, response.body), trace_id)
            return 0.0  # the rest of the batch goes again right away
        if outcome is Outcome.FORBIDDEN:
            log("batch_forbidden", level="error", stream=self.stream.name, traceId=trace_id, count=count,
                hint="the token is not a device token: check COGNITO_CLIENT_ID and the device account")
            return self._rest(FORBIDDEN_WAIT_SECONDS)
        if account_fault(response) is None:
            self.faults.failed(self.stream.fault)
        log("batch_failed", level="warning", stream=self.stream.name, traceId=trace_id, count=count, status=status)
        return self._rest(max(self.backoff.next_delay(), retry_after(response.headers) or 0.0))

    def _quarantine(self, batch: Batch[T], problem: Problem, trace_id: str) -> None:
        bad = [q.row_id for i, q in enumerate(batch.queued) if i in problem.indexes] or batch.row_ids
        code = problem.code or f"HTTP {problem.status}"
        self.stream.queue.quarantine(bad, problem.status, code)
        # The field codes name the rule broken, never the value, so they are safe to log.
        log("items_quarantined", level="error", stream=self.stream.name, traceId=trace_id, count=len(bad),
            status=problem.status, code=code,
            fields=[{"index": f.index, "field": f.field, "code": f.code} for f in problem.fields][:LOGGED_FIELD_ERRORS])
