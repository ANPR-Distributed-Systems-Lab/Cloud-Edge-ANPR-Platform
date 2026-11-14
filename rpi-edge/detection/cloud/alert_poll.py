"""Polls the alert list of the owner (GET /api/v1/alerts of operations-service) with If-None-Match.

200 replaces the list in memory, 304 means nothing changed. A failed poll keeps the list it has. The interval is
intervals.alertsPollSeconds of the device configuration (every UNCONFIGURED_POLL_SECONDS before there is one).
"""
import threading

from common.jsonlog import log
from detection.cloud.api import Api
from detection.cloud.cognito import AuthError
from detection.cloud.transport import NetworkError
from detection.config.store import ConfigurationStore
from detection.contract.alerts import AlertList
from detection.contract.parsing import ContractError
from detection.contract.problem import Problem
from detection.contract.wire import uuid7
from detection.rules.alerts import AlertWatch

UNCONFIGURED_POLL_SECONDS = 10.0


class AlertPoller:
    def __init__(self, api: Api, url: str, watch: AlertWatch, configuration: ConfigurationStore) -> None:
        self.api = api
        self.url = url
        self.watch = watch
        self.configuration = configuration

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.poll_once()
            except Exception as e:  # never let the poller thread die
                log("alert_poll_error", level="error", error=repr(e))
            current = self.configuration.current
            stop.wait(current.intervals.alerts_poll_seconds if current else UNCONFIGURED_POLL_SECONDS)

    def poll_once(self) -> None:
        trace_id = uuid7()
        etag = self.watch.etag
        try:
            response = self.api.request("GET", self.url, trace_id=trace_id,
                                        headers={"If-None-Match": etag} if etag else None)
        except (NetworkError, AuthError) as e:
            log("alert_poll_failed", level="warning", traceId=trace_id, error=str(e))
            return
        if response.status == 304:
            return
        if response.status != 200:
            log("alert_poll_failed", level="warning", traceId=trace_id, status=response.status,
                code=Problem.of(response.status, response.body).code)
            return
        try:
            alerts = AlertList.from_document(response.json())
        except (ContractError, ValueError) as e:
            log("alert_list_refused", level="error", traceId=trace_id,
                problems=e.problems if isinstance(e, ContractError) else [str(e)])
            return
        self.watch.replace(alerts, response.headers.get("etag"))
        log("alert_list_updated", traceId=trace_id, alerts=len(alerts.items))
