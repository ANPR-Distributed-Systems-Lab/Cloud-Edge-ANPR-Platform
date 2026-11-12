"""The settings the detection mode runs with, as typed, immutable values.

Documents (the defaults, /config/detection.json, the cloud configuration) use the field names of the device
configuration contract (device-management-api.yaml): camelCase, the same nesting. EdgeSettings.from_document()
maps them onto these dataclasses (a field `ocr_min_confidence` reads the key `ocrMinConfidence`) and checks every
value against the range or choices of its field, so the rest of the mode never touches a raw document.
"""
from dataclasses import dataclass, field, fields, is_dataclass
from typing import get_type_hints


class SettingsError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def bounded(low: float, high: float):
    return field(metadata={"range": (low, high)})


def one_of(*choices: str):
    return field(metadata={"choices": choices})


@dataclass(frozen=True)
class MlSettings:
    detector_min_confidence: float = bounded(0, 1)
    ocr_min_confidence: float = bounded(0, 1)
    readable_min_probability: float = bounded(0, 1)  # not in the cloud contract yet
    min_plate_width_px: int = bounded(10, 4056)
    min_edge_margin_px: int = bounded(0, 1000)  # not in the cloud contract yet


@dataclass(frozen=True)
class BatchingSettings:
    detections_batch_size: int = bounded(1, 100)
    max_batch_delay_seconds: float = bounded(1, 300)


@dataclass(frozen=True)
class IntervalsSettings:
    config_poll_seconds: float = bounded(3, 3600)


@dataclass(frozen=True)
class ExposureSettings:
    mode: str = one_of("MANUAL", "AUTO", "AUTO_GAIN", "AUTO_EXPOSURE")
    exposure_us: int = bounded(20, 1_000_000)
    gain: float = bounded(1, 22)
    max_exposure_us: int = bounded(20, 1_000_000)
    max_gain: float = bounded(1, 22)
    target_brightness: float = bounded(0.1, 0.8)


@dataclass(frozen=True)
class WhiteBalanceSettings:
    mode: str = one_of("AUTO", "DAYLIGHT", "CLOUDY", "TUNGSTEN", "FLUORESCENT", "INDOOR", "MANUAL")
    red_gain: float = bounded(0.5, 8)
    blue_gain: float = bounded(0.5, 8)


@dataclass(frozen=True)
class CameraSettings:
    fps: float = bounded(0.1, 11.7)  # the most frames analysed per second
    exposure: ExposureSettings
    white_balance: WhiteBalanceSettings
    hflip: bool  # local only: how the camera is mounted, as for the training frames
    vflip: bool


@dataclass(frozen=True)
class EdgeSettings:
    plate_cooldown_seconds: float = bounded(0, 3600)
    batching: BatchingSettings
    ml: MlSettings
    intervals: IntervalsSettings
    camera: CameraSettings

    @classmethod
    def from_document(cls, document: dict) -> "EdgeSettings":
        """Raises SettingsError listing every field that is missing or outside the contract."""
        return _build(cls, document, "settings")


def _camel(name: str) -> str:
    first, *rest = name.split("_")
    return first + "".join(part.capitalize() for part in rest)


def _build(cls, document, path: str):
    """path names the document in messages: "settings" for the root, then e.g. "camera.exposure"."""
    if not isinstance(document, dict):
        raise SettingsError([f"{path} must be an object"])
    values, problems = {}, []
    types = get_type_hints(cls)
    for f in fields(cls):
        key = _camel(f.name)
        where = key if path == "settings" else f"{path}.{key}"
        raw, kind = document.get(key), types[f.name]
        try:
            values[f.name] = _build(kind, raw, where) if is_dataclass(kind) else _value(raw, kind, f.metadata, where)
        except SettingsError as e:
            problems += e.problems
    if problems:
        raise SettingsError(problems)
    return cls(**values)


def _value(raw, kind, metadata, key: str):
    # bool is checked first: in Python True is also an int, and 1 is not a boolean here.
    if kind is bool:
        if not isinstance(raw, bool):
            raise SettingsError([f"{key} must be true or false"])
        return raw
    if kind is str:
        if raw not in metadata["choices"]:
            raise SettingsError([f"{key} must be one of {', '.join(metadata['choices'])}"])
        return raw
    low, high = metadata["range"]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not low <= raw <= high:
        raise SettingsError([f"{key} must be a number from {low} to {high}"])
    return kind(raw)
