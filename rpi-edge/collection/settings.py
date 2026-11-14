"""User-facing capture settings, persisted as JSON so recording uses exactly what was tuned in the UI."""
import copy
import json
import os
import threading

CONFIG_DIR = os.environ.get("CONFIG_DIR", "/config")
SETTINGS_PATH = os.path.join(CONFIG_DIR, "settings.json")

# Record resolutions: name -> (width, height). Lores preview is derived from the aspect ratio.
RESOLUTIONS = {
    "4056x3040": (4056, 3040),
    "4056x2160": (4056, 2160),
    "2028x1520": (2028, 1520),
    "2028x1080": (2028, 1080),
    "1332x990": (1332, 990),
}

# Max sensor fps of the sensor mode libcamera picks for each resolution (12-bit modes, the default).
# Measured with `rpicam-hello --list-cameras` on the IMX477.
MAX_SENSOR_FPS = {
    "4056x3040": 11.7,
    "4056x2160": 16.3,
    "2028x1520": 45.0,
    "2028x1080": 62.0,
    "1332x990": 101.0,
}

EXPOSURE_MODES = ("manual", "auto", "auto_gain", "auto_exposure")
WB_MODES = ("auto", "daylight", "cloudy", "tungsten", "fluorescent", "indoor", "manual")

DEFAULTS = {
    "exposure": {
        # manual:        exposure_us and gain fixed
        # auto:          brightness balanced by exposure time first (up to max_exposure_us), then gain (up to max_gain)
        # auto_gain:     exposure_us fixed, gain automatic (up to max_gain)
        # auto_exposure: gain fixed, exposure time automatic (up to max_exposure_us)
        "mode": "manual",
        "exposure_us": 2000,
        "gain": 4.0,
        "max_exposure_us": 4000,
        "max_gain": 12.0,
        "target_brightness": 0.40,  # 0..1, mean of the metered area. Slightly dark protects bright plates/headlights.
    },
    "white_balance": {"mode": "daylight", "red_gain": 2.0, "blue_gain": 1.6},
    "recording": {
        "fps": 2.0,
        "resolution": "4056x3040",
        "jpeg_quality": 92,
        "min_free_mb": 500,  # recording stops when the USB stick has less free space than this
        "autostart": False,  # start recording by itself right after boot once the USB stick is available
    },
    # Only flips are available in hardware (rot180 = both). The Pi 5 pipeline cannot rotate by 90 degrees.
    "camera": {"hflip": False, "vflip": False},
    "focus_roi": {"x": 0.5, "y": 0.5},  # centre of the 1:1 focus view, 0..1 of the frame
}


def _num(value, low, high, default):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return round(min(max(value, low), high), 3)  # 3 decimals: no 3.2508127 in the saved JSON


def sanitize(raw: dict) -> dict:
    """Merge `raw` over the defaults and clamp every value to something the camera can handle."""
    s = copy.deepcopy(DEFAULTS)
    ex, wb, rec, roi, cam = (raw.get(k) or {} for k in ("exposure", "white_balance", "recording", "focus_roi", "camera"))

    if ex.get("mode") in EXPOSURE_MODES:
        s["exposure"]["mode"] = ex["mode"]
    s["exposure"]["exposure_us"] = int(_num(ex.get("exposure_us"), 20, 1_000_000, DEFAULTS["exposure"]["exposure_us"]))
    s["exposure"]["gain"] = _num(ex.get("gain"), 1.0, 22.0, DEFAULTS["exposure"]["gain"])
    s["exposure"]["max_exposure_us"] = int(_num(ex.get("max_exposure_us"), 20, 1_000_000, DEFAULTS["exposure"]["max_exposure_us"]))
    s["exposure"]["max_gain"] = _num(ex.get("max_gain"), 1.0, 22.0, DEFAULTS["exposure"]["max_gain"])
    s["exposure"]["target_brightness"] = _num(ex.get("target_brightness"), 0.1, 0.8, DEFAULTS["exposure"]["target_brightness"])

    if wb.get("mode") in WB_MODES:
        s["white_balance"]["mode"] = wb["mode"]
    s["white_balance"]["red_gain"] = _num(wb.get("red_gain"), 0.5, 8.0, DEFAULTS["white_balance"]["red_gain"])
    s["white_balance"]["blue_gain"] = _num(wb.get("blue_gain"), 0.5, 8.0, DEFAULTS["white_balance"]["blue_gain"])

    if rec.get("resolution") in RESOLUTIONS:
        s["recording"]["resolution"] = rec["resolution"]
    limit = MAX_SENSOR_FPS[s["recording"]["resolution"]]
    s["recording"]["fps"] = _num(rec.get("fps"), 0.1, limit, min(DEFAULTS["recording"]["fps"], limit))
    s["recording"]["jpeg_quality"] = int(_num(rec.get("jpeg_quality"), 50, 100, DEFAULTS["recording"]["jpeg_quality"]))
    s["recording"]["min_free_mb"] = int(_num(rec.get("min_free_mb"), 50, 100_000, DEFAULTS["recording"]["min_free_mb"]))
    s["recording"]["autostart"] = bool(rec.get("autostart", DEFAULTS["recording"]["autostart"]))

    s["camera"]["hflip"] = bool(cam.get("hflip", False))
    s["camera"]["vflip"] = bool(cam.get("vflip", False))

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
