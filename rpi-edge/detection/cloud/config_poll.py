"""Polls the device configuration of device-management (GET /api/v1/device/config) with If-None-Match.

200 replaces the configuration (and its copy on the device), 304 means nothing changed. A failed poll or a
configuration outside the contract keeps the current one and is tried again at the next interval; until the
device has its first configuration it asks every UNCONFIGURED_POLL_SECONDS.

Faults (common/fault_catalog.py): no configuration (none after a poll), config refused (outside the contract) and
config poll failed (error answers in a row; the device runs on its copy but no change arrives). Each clears with
the next configuration taken; an error answer that a fault of the account explains (cloud/api.py) counts only
there. No answer at all is not a fault: the network LED shows it.
"""
import threading

from common import fault_catalog as kinds
from common.faults import FaultBoard
from common.jsonlog import log
from detection.cloud.api import Api, account_fault
from detection.cloud.cognito import AuthError
from detection.cloud.transport import NetworkError
from detection.config.store import ConfigurationStore
from detection.contract.parsing import ContractError
from detection.contract.problem import Problem
from detection.contract.wire import uuid7

UNCONFIGURED_POLL_SECONDS = 10.0


class ConfigPoller:
    def __init__(self, api: Api, url: str, store: ConfigurationStore, faults: FaultBoard) -> None:
        self.api = api
        self.url = url
        self.store = store
        self.faults = faults

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.poll_once()
            except Exception as e:  # never let the poller thread die
                log("config_poll_error", level="error", error=repr(e))
            current = self.store.current
            if current is None:
                self.faults.report(kinds.NO_CONFIG)
            stop.wait(current.intervals.config_poll_seconds if current else UNCONFIGURED_POLL_SECONDS)

    def poll_once(self) -> None:
        trace_id = uuid7()
        etag = self.store.etag
        try:
            response = self.api.request("GET", self.url, trace_id=trace_id,
                                        headers={"If-None-Match": etag} if etag else None)
        except (NetworkError, AuthError) as e:
            log("config_poll_failed", level="warning", traceId=trace_id, error=str(e))
            return
        if response.status == 304:
            self.faults.succeeded(kinds.CONFIG_POLL_FAILED)
            return
        if response.status != 200:
            if account_fault(response) is None:
                self.faults.failed(kinds.CONFIG_POLL_FAILED)
            log("config_poll_failed", level="warning", traceId=trace_id, status=response.status,
                code=Problem.of(response.status, response.body).code)
            return
        self.faults.succeeded(kinds.CONFIG_POLL_FAILED)
        try:
            changed = self.store.apply(response.json(), response.headers.get("etag"))
        except (ContractError, ValueError) as e:
            self.faults.report(kinds.CONFIG_REFUSED)
            log("configuration_refused", level="error", traceId=trace_id,
                problems=e.problems if isinstance(e, ContractError) else [str(e)])
            return
        self.faults.clear(kinds.CONFIG_REFUSED, kinds.NO_CONFIG)
        if changed:
            log("configuration_updated", traceId=trace_id, configVersion=self.store.current.version)
