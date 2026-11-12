"""The device configuration of device-management (GET /api/v1/device/config, DeviceConfigurationResponse).

It is the only source of the settings of the detection mode: device-management holds the defaults and the owner
edits them (View 4); the device keeps a copy (config/store.py). The ranges below are those of the contract.
"""
from dataclasses import dataclass

from detection.contract.parsing import bounded, matching, one_of, parse

UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
MODEL_VERSION = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"  # also a directory name in the model cache


@dataclass(frozen=True)
class BatchingConfiguration:
    detections_batch_size: int = bounded(1, 100)  # detections per ingest request
    locations_batch_size: int = bounded(1, 500)  # GPS points per request (not used yet)
    image_urls_batch_size: int = bounded(1, 100)  # frames per presigned URL request (not used yet)
    max_batch_delay_seconds: int = bounded(1, 300)  # a batch that is not full leaves after this long


@dataclass(frozen=True)
class MlConfiguration:
    """The send rule (rules/send_rule.py)."""
    detector_min_confidence: float = bounded(0, 1)
    ocr_min_confidence: float = bounded(0, 1)
    readable_min_probability: float = bounded(0, 1)
    min_plate_width_px: int = bounded(10, 4056)
    min_edge_margin_px: int = bounded(0, 1000)


@dataclass(frozen=True)
class ModelVersions:
    """The published model versions the device runs (cloud/model_updater.py)."""
    detector: str = matching(MODEL_VERSION)
    ocr: str = matching(MODEL_VERSION)


@dataclass(frozen=True)
class IntervalsConfiguration:
    metrics_seconds: int = bounded(3, 3600)  # not used yet
    config_poll_seconds: int = bounded(3, 3600)
    alerts_poll_seconds: int = bounded(3, 3600)  # not used yet
    location_sample_seconds: int = bounded(1, 60)  # not used yet


@dataclass(frozen=True)
class ExposureConfiguration:
    mode: str = one_of("MANUAL", "AUTO", "AUTO_GAIN", "AUTO_EXPOSURE")
    exposure_us: int = bounded(20, 1_000_000)
    gain: float = bounded(1, 22)
    max_exposure_us: int = bounded(20, 1_000_000)
    max_gain: float = bounded(1, 22)
    target_brightness: float = bounded(0.1, 0.8)


@dataclass(frozen=True)
class WhiteBalanceConfiguration:
    mode: str = one_of("AUTO", "DAYLIGHT", "CLOUDY", "TUNGSTEN", "FLUORESCENT", "INDOOR", "MANUAL")
    red_gain: float = bounded(0.5, 8)
    blue_gain: float = bounded(0.5, 8)


@dataclass(frozen=True)
class CameraConfiguration:
    exposure: ExposureConfiguration
    white_balance: WhiteBalanceConfiguration
    fps: float = bounded(0.1, 11.7)  # the most frames analysed per second
    hflip: bool  # how the camera is mounted, so the models see the scene upright and unmirrored
    vflip: bool


@dataclass(frozen=True)
class DeviceConfiguration:
    device_id: str = matching(UUID)
    version: int = bounded(0, 2**63 - 1)  # changes with every edit of the owner
    updated_at: str = matching(r".+")
    plate_cooldown_seconds: int = bounded(0, 3600)
    batching: BatchingConfiguration
    ml: MlConfiguration
    models: ModelVersions
    intervals: IntervalsConfiguration
    camera: CameraConfiguration

    @classmethod
    def from_document(cls, document) -> "DeviceConfiguration":
        """Raises ContractError naming every field that is missing or outside the contract."""
        return parse(cls, document)
