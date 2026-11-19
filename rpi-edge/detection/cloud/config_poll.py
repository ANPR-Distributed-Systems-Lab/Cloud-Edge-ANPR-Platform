"""Polls the device configuration of device-management (GET /api/v1/device/config) with If-None-Match.

200 replaces the configuration (and its copy on the device), 304 means nothing changed. A failed poll or a
configuration outside the contract keeps the current one and is tried again at the next interval; until the
device has its first configuration it asks every UNCONFIGURED_POLL_SECONDS.

Faults (common/faults.py): a refused configuration, a device that is not paired (404) and a device that has no
configuration at all after a poll; each clears with the next configuration taken.
"""
import threading

from common.faults import FaultBoard
from common.jsonlog import log
from detection.cloud.api import Api
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
                self.faults.report("no_config", "no configuration")
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
            self.faults.clear("config_refused", "not_paired")
            return
        if response.status != 200:
            problem = Problem.of(response.status, response.body)
            # 404: the device is not (or no longer) paired, which no retry fixes.
            if response.status == 404:
                self.faults.report("not_paired", "device not paired")
            log("config_poll_failed", level="error" if response.status == 404 else "warning", traceId=trace_id,
                status=response.status, code=problem.code)
            return
        try:
            changed = self.store.apply(response.json(), response.headers.get("etag"))
        except (ContractError, ValueError) as e:
            self.faults.report("config_refused", "config refused")
            log("configuration_refused", level="error", traceId=trace_id,
                problems=e.problems if isinstance(e, ContractError) else [str(e)])
            return
        self.faults.clear("config_refused", "not_paired", "no_config")
        if changed:
            log("configuration_updated", traceId=trace_id, configVersion=self.store.current.version)
