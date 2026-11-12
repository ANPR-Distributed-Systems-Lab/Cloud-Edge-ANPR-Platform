"""Polls the device configuration of device-management (GET /api/v1/device/config) with If-None-Match.

200 replaces the cloud layer of the settings (and its cached copy), 304 means nothing changed. A failed poll
keeps the settings as they are and tries again at the next interval.
"""
import threading

from common.jsonlog import log
from detection.cloud.api import Api
from detection.cloud.cognito import AuthError
from detection.cloud.transport import NetworkError
from detection.config.settings import Settings
from detection.delivery.events import uuid7


class ConfigPoller:
    def __init__(self, api: Api, url: str, settings: Settings) -> None:
        self.api = api
        self.url = url
        self.settings = settings

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                self.poll_once()
            except Exception as e:  # never let the poller thread die
                log("config_poll_error", level="error", error=repr(e))
            stop.wait(self.settings.current.intervals.config_poll_seconds)

    def poll_once(self) -> None:
        trace_id = uuid7()
        etag = self.settings.cloud_etag
        try:
            response = self.api.request("GET", self.url, trace_id=trace_id,
                                        headers={"If-None-Match": etag} if etag else None)
        except (NetworkError, AuthError) as e:
            log("config_poll_failed", level="warning", traceId=trace_id, error=str(e))
            return
        if response.status == 304:
            return
        if response.status == 200:
            document = response.json() or {}
            if self.settings.apply_cloud(document, response.headers.get("etag")):
                log("settings_updated", traceId=trace_id, source="cloud", configVersion=document.get("version"))
            return
        if response.status == 404:
            log("device_not_registered", level="error", traceId=trace_id)
            return
        log("config_poll_failed", level="warning", traceId=trace_id, status=response.status)
