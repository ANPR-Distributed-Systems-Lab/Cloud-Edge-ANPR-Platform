"""How the detection mode behaves (DETECTION.md, "Configuration"). Three layers, each overriding the one before:

  1. DEFAULTS below,
  2. /config/detection.json, edited by hand on the device (the camera mounting, development),
  3. the device configuration of device-management (GET /api/v1/device/config), cached in /config/cloud-config.json
     so it applies after a restart without network.

Layers are documents with the field names of the device configuration contract, merged field by field. A layer
whose result breaks the contract (config/schema.py) is ignored as a whole, so a typo never half-applies.
"""
import copy
import json
import threading
from pathlib import Path

from common.files import write_json_atomic
from common.jsonlog import log
from detection.config.schema import EdgeSettings, SettingsError

DEFAULTS = {
    "plateCooldownSeconds": 60,
    "batching": {"detectionsBatchSize": 20, "maxBatchDelaySeconds": 10},
    "ml": {
        # Starting points of the ML send-rule analysis on val (ML_ASSUMPTIONS.md, section 9); still OPEN.
        "detectorMinConfidence": 0.40,
        "ocrMinConfidence": 0.80,
        "readableMinProbability": 0.80,
        "minPlateWidthPx": 70,
        "minEdgeMarginPx": 10,
    },
    "intervals": {"configPollSeconds": 60},
    "camera": {
        "fps": 3.0,
        "exposure": {"mode": "AUTO", "exposureUs": 500, "gain": 2.0, "maxExposureUs": 540, "maxGain": 4.0,
                     "targetBrightness": 0.4},
        "whiteBalance": {"mode": "DAYLIGHT", "redGain": 2.0, "blueGain": 1.6},
        "hflip": False,
        "vflip": False,
    },
}
CLOUD_SECTIONS = ("plateCooldownSeconds", "batching", "ml", "intervals", "camera")


def merge(base: dict, override: dict) -> dict:
    """Deep merge: dictionaries are merged key by key, any other value replaces the one in base."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def default_settings() -> EdgeSettings:
    return EdgeSettings.from_document(DEFAULTS)


class Settings:
    """The effective settings. `current` is replaced as a whole on every change, so readers never see a half update;
    `version` goes up with each change, so the camera knows when to re-apply them."""

    def __init__(self, config_dir: Path) -> None:
        self.local_file = config_dir / "detection.json"
        self.cloud_file = config_dir / "cloud-config.json"
        self._lock = threading.Lock()
        cached = _read_document(self.cloud_file)
        self._cloud: dict = cached.get("configuration", {})
        self.cloud_etag: str | None = cached.get("etag")
        self.version = 0
        self.current = self._effective()

    def apply_cloud(self, document: dict, etag: str | None) -> bool:
        """Takes the device configuration of device-management. Returns True when the settings changed."""
        configuration = {k: document[k] for k in CLOUD_SECTIONS if k in document}
        with self._lock:
            self._cloud, self.cloud_etag = configuration, etag
            write_json_atomic(self.cloud_file, {"etag": etag, "configuration": configuration})
            effective = self._effective()
            if effective == self.current:
                return False
            self.current = effective
            self.version += 1
            return True

    def _effective(self) -> EdgeSettings:
        document, settings = DEFAULTS, default_settings()
        for name, layer in (("local", _read_document(self.local_file)), ("cloud", self._cloud)):
            candidate = merge(document, layer)
            try:
                settings, document = EdgeSettings.from_document(candidate), candidate
            except SettingsError as e:
                log("settings_layer_ignored", level="error", layer=name, problems=e.problems)
        return settings


def _read_document(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8-sig") as f:  # tolerates the BOM some Windows tools write
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log("settings_file_unreadable", level="error", file=str(path), error=str(e))
        return {}
