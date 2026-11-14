"""Valid contract documents for tests; each call returns a new copy that a test may change."""
import copy
from datetime import UTC, datetime

from detection.contract.configuration import DeviceConfiguration
from detection.contract.ingest import DetectionEvent
from detection.contract.locations import Location
from detection.contract.wire import iso_ms

DEVICE_ID = "7d3f2c1e-0000-4000-8000-000000000000"

_CONFIGURATION = {
    "deviceId": DEVICE_ID,
    "version": 3,
    "updatedAt": "2026-11-12T10:00:00Z",
    "plateCooldownSeconds": 60,
    "batching": {"detectionsBatchSize": 20, "locationsBatchSize": 100, "imageUrlsBatchSize": 20,
                 "maxBatchDelaySeconds": 10},
    "ml": {"detectorMinConfidence": 0.40, "ocrMinConfidence": 0.80, "readableMinProbability": 0.80,
           "minPlateWidthPx": 70, "minEdgeMarginPx": 10},
    "models": {"detector": "v2", "ocr": "v3"},
    "intervals": {"metricsSeconds": 60, "configPollSeconds": 60, "alertsPollSeconds": 60, "locationSampleSeconds": 5},
    "camera": {
        "exposure": {"mode": "AUTO", "exposureUs": 500, "gain": 2.0, "maxExposureUs": 540, "maxGain": 4.0,
                     "targetBrightness": 0.4},
        "whiteBalance": {"mode": "DAYLIGHT", "redGain": 2.0, "blueGain": 1.6},
        "fps": 3.0,
        "hflip": True,
        "vflip": True,
    },
}


def merge(base: dict, patch: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in patch.items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def configuration_document(**patch) -> dict:
    """The configuration document with the given top-level sections merged in, e.g. ml={"ocrMinConfidence": 0.9}."""
    return merge(_CONFIGURATION, patch)


def configuration(**patch) -> DeviceConfiguration:
    return DeviceConfiguration.from_document(configuration_document(**patch))


# The position of the examples of the contract (docs/api/ingest-detections.md): nothing real is ever in a test.
LOCATION = Location(52.229676, 21.012229, 4.5, 300)


FRAME_ID = "0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c"


def detection_event(n: int, at: float = 0.0, plate: str = "WA12345") -> DetectionEvent:
    """Detection n, captured `at` Unix seconds."""
    captured = datetime.fromtimestamp(at, UTC)
    return DetectionEvent(f"id-{n}", FRAME_ID, captured, plate, 0.9, 0.8,
                          f"images/{DEVICE_ID}/{captured:%Y/%m/%d}/{FRAME_ID}.jpg",
                          ((0.1, 0.1), (0.2, 0.1), (0.2, 0.12), (0.1, 0.12)), LOCATION)


def wire_time(at: float) -> str:
    return iso_ms(datetime.fromtimestamp(at, UTC))
