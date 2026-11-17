"""User-facing capture settings, persisted as JSON so recording uses exactly what was tuned in the UI.

The settings stay a JSON document (the shape the page edits and session.json records): the page sends partial
updates, which are merged and clamped here. The resolution is fixed to the full sensor (common/sensor.py), as in
the detection mode.
"""
import copy
import json
import os
import threading

from common.sensor import MAX_EXPOSURE_US, MAX_FPS

CONFIG_DIR = os.environ.get("CONFIG_DIR", "/config")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")

EXPOSURE_MODES = ("manual", "auto", "auto_gain", "auto_exposure")
WB_MODES = ("auto", "daylight", "cloudy", "tungsten", "fluorescent", "indoor", "manual")
STEP = 0.001  # settings keep 3 decimals (_num), so a band is at least this tall

# The camera settings start as the defaults of a new device in device-management (its application.yaml), so a value
# tried here means the same in the device configuration, where the owner enters it by hand (View 4): the same modes,
# ranges and metered band. Lower case and snake_case here, upper case and camelCase there.
DEFAULTS = {
    "exposure": {
        # manual:        exposure_us and gain fixed
        # auto:          brightness balanced by exposure time first (up to max_exposure_us), then gain (up to max_gain)
        # auto_gain:     exposure_us fixed, gain automatic (up to max_gain)
        # auto_exposure: gain fixed, exposure time automatic (up to max_exposure_us)
        "mode": "auto",
        "exposure_us": 500,
        "gain": 2.0,
        "max_exposure_us": 540,
        "max_gain": 4.0,
        "target_brightness": 0.40,  # 0..1, mean of the metered band. Slightly dark protects bright plates/headlights.
        # The rows the automatic modes measure, shares of the frame height at full width: the band of detector v3,
        # where the plates pass. The preview shows it as two lines.
        "metering_top": 0.337,
        "metering_bottom": 0.795,
    },
    "white_balance": {"mode": "daylight", "red_gain": 2.0, "blue_gain": 1.6},
    "recording": {
        "fps": 2.0,
        "jpeg_quality": 92,
        "min_free_mb": 500,  # recording stops when the USB stick has less free space than this
        "autostart": False,  # start recording by itself right after boot once the USB stick is available
    },
    # Only flips are available in hardware (rot180 = both). The devices built so far hold the camera upside down.
    "camera": {"hflip": True, "vflip": True},
    "focus_roi": {"x": 0.5, "y": 0.5},  # centre of the 1:1 focus view, 0..1 of the frame
}


def _num(value, low, high, default):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return round(min(max(value, low), high), 3)  # 3 decimals: no 3.2508127 in the saved JSON


def sanitize(raw: dict) -> dict:
    """Merge `raw` over the defaults and clamp every value to the ranges of the device configuration."""
    s = copy.deepcopy(DEFAULTS)
    sections = ("exposure", "white_balance", "recording", "focus_roi", "camera")
    ex, wb, rec, roi, cam = (raw.get(k) or {} for k in sections)
    d_ex, d_wb, d_rec = DEFAULTS["exposure"], DEFAULTS["white_balance"], DEFAULTS["recording"]

    if ex.get("mode") in EXPOSURE_MODES:
        s["exposure"]["mode"] = ex["mode"]
    s["exposure"]["exposure_us"] = int(_num(ex.get("exposure_us"), 20, MAX_EXPOSURE_US, d_ex["exposure_us"]))
    s["exposure"]["gain"] = _num(ex.get("gain"), 1.0, 22.0, d_ex["gain"])
    s["exposure"]["max_exposure_us"] = int(_num(ex.get("max_exposure_us"), 20, MAX_EXPOSURE_US,
                                                d_ex["max_exposure_us"]))
    s["exposure"]["max_gain"] = _num(ex.get("max_gain"), 1.0, 22.0, d_ex["max_gain"])
    s["exposure"]["target_brightness"] = _num(ex.get("target_brightness"), 0.1, 0.8, d_ex["target_brightness"])
    # The ranges of the configuration contract: top 0-0.95, bottom 0.05-1, and the bottom below the top.
    top = _num(ex.get("metering_top"), 0.0, 0.95, d_ex["metering_top"])
    lowest_bottom = max(0.05, round(top + STEP, 3))
    s["exposure"]["metering_top"] = top
    s["exposure"]["metering_bottom"] = _num(ex.get("metering_bottom"), lowest_bottom, 1.0,
                                            max(d_ex["metering_bottom"], lowest_bottom))

    if wb.get("mode") in WB_MODES:
        s["white_balance"]["mode"] = wb["mode"]
    s["white_balance"]["red_gain"] = _num(wb.get("red_gain"), 0.5, 8.0, d_wb["red_gain"])
    s["white_balance"]["blue_gain"] = _num(wb.get("blue_gain"), 0.5, 8.0, d_wb["blue_gain"])

    s["recording"]["fps"] = _num(rec.get("fps"), 0.1, MAX_FPS, d_rec["fps"])
    s["recording"]["jpeg_quality"] = int(_num(rec.get("jpeg_quality"), 50, 100, d_rec["jpeg_quality"]))
    s["recording"]["min_free_mb"] = int(_num(rec.get("min_free_mb"), 50, 100_000, d_rec["min_free_mb"]))
    s["recording"]["autostart"] = bool(rec.get("autostart", d_rec["autostart"]))

    s["camera"]["hflip"] = bool(cam.get("hflip", DEFAULTS["camera"]["hflip"]))
    s["camera"]["vflip"] = bool(cam.get("vflip", DEFAULTS["camera"]["vflip"]))

    s["focus_roi"]["x"] = _num(roi.get("x"), 0.0, 1.0, 0.5)
    s["focus_roi"]["y"] = _num(roi.get("y"), 0.0, 1.0, 0.5)
    return s


class SettingsStore:
    def __init__(self, path: str = SETTINGS_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._value = DEFAULTS
        self._value = sanitize(self._read())

    def _read(self) -> dict:
        try:
            with open(self._path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def get(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._value)

    def update(self, patch: dict) -> dict:
        """Deep-merge a partial update, validate it, save it atomically and return the result."""
        with self._lock:
            merged = copy.deepcopy(self._value)
            for section, values in patch.items():
                if section in merged and isinstance(values, dict):
                    merged[section].update(values)
            self._value = sanitize(merged)
            self._save()
            return copy.deepcopy(self._value)

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._value, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)
