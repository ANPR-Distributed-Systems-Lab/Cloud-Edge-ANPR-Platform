"""The configuration the detection mode runs with: the device configuration of device-management, nothing else.

Every setting (send rule thresholds, model versions, camera, batching, intervals) is kept and edited in the
cloud, which also holds the defaults. The device keeps the last configuration it received in
/config/device-config.json, so after a restart without network it runs on that copy. A device that never
received one waits for it (cloud/config_poll.py fetches it).
"""
import json
import threading
from pathlib import Path

from common.files import write_json_atomic
from common.jsonlog import log
from detection.contract.configuration import DeviceConfiguration
from detection.contract.parsing import ContractError

CACHE_FILE = "device-config.json"


class ConfigurationStore:
    """`current` is replaced as a whole, so readers never see half an update; `version` goes up with every change,
    so the frame loop knows when to re-apply the camera settings."""

    def __init__(self, config_dir: Path) -> None:
        self.cache_file = config_dir / CACHE_FILE
        self.current: DeviceConfiguration | None = None
        self.etag: str | None = None
        self.version = 0
        self._configured = threading.Event()
        self._lock = threading.Lock()
        self._load_cached()

    def apply(self, document: dict, etag: str | None) -> bool:
        """Takes a configuration from the cloud and keeps a copy. Returns True when it differs from the current one.

        Raises ContractError for a document outside the contract; the current configuration then stays.
        """
        configuration = DeviceConfiguration.from_document(document)
        with self._lock:
            write_json_atomic(self.cache_file, {"etag": etag, "configuration": document})
            self.etag = etag
            if configuration == self.current:
                return False
            self.current = configuration
            self.version += 1
            self._configured.set()
            return True

    def wait_until_configured(self, stop: threading.Event) -> DeviceConfiguration | None:
        """Blocks until there is a configuration (None if stopped first)."""
        while not stop.is_set():
            if self._configured.wait(timeout=1.0):
                return self.current
        return None

    def _load_cached(self) -> None:
        try:
            with open(self.cache_file, encoding="utf-8") as f:
                cached = json.load(f)
            self.current = DeviceConfiguration.from_document(cached["configuration"])
        except FileNotFoundError:
            log("configuration_missing", level="warning", hint="waiting for GET /api/v1/device/config")
            return
        except (OSError, ValueError, KeyError, TypeError) as e:
            problems = e.problems if isinstance(e, ContractError) else [str(e)]
            log("configuration_cache_unusable", level="error", file=str(self.cache_file), problems=problems)
            return
        self.etag = cached.get("etag")
        self.version = 1
        self._configured.set()
        log("configuration_from_cache", configVersion=self.current.version)
