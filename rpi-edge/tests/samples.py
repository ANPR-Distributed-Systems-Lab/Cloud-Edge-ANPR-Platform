"""Valid contract documents for tests; each call returns a new copy that a test may change."""
import copy

from detection.contract.configuration import DeviceConfiguration

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
