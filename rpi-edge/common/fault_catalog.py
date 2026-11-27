"""Every fault of the device, by mode. What each one means, when it lights and when it clears: INDICATORS.md (a test
keeps the two in step). The text with its detail stays within the 20 columns of the LCD.
"""
from common.faults import Fault, FaultKind

RETRIED = 3  # failed attempts in a row before a fault of something retried lights: one 503 is not a fault

# --- both modes: the Pi itself, measured ------------------------------------------------------------------------
UNDERVOLTAGE = FaultKind("undervoltage", "power too low")
THROTTLED = FaultKind("throttled", "CPU throttled")
CPU_HOT = FaultKind("cpu_hot", "CPU hot")  # + "82C"

# --- detection: the configuration (cloud/config_poll.py) -------------------------------------------------------
NO_CONFIG = FaultKind("no_config", "no configuration")
CONFIG_REFUSED = FaultKind("config_refused", "config refused")
CONFIG_POLL_FAILED = FaultKind("config_poll_failed", "config poll failed", RETRIED)

# --- detection: the device and its account, from any request (cloud/api.py, cloud/cognito.py) -------------------
NO_CREDENTIALS = FaultKind("no_credentials", "no credentials")
SIGN_IN_REFUSED = FaultKind("sign_in_refused", "sign-in refused")
TOKEN_REFUSED = FaultKind("token_refused", "token refused (401)")
NOT_DEVICE_TOKEN = FaultKind("not_device_token", "not a device token")
DEVICE_NOT_FOUND = FaultKind("device_not_found", "device not found")
NO_OWNER = FaultKind("no_owner", "device has no owner")

# --- detection: the models (cloud/model_updater.py) ------------------------------------------------------------
NO_MODELS = FaultKind("no_models", "no models")
MODEL_NOT_PUBLISHED = FaultKind("model_not_published", "model not published")
MODELS_NOT_UPDATED = FaultKind("models_not_updated", "models not updated", RETRIED)
MODEL_LOAD_FAILED = FaultKind("model_load_failed", "model load failed")

# --- detection: sending (delivery/sender.py, delivery/uploads.py) ----------------------------------------------
PLATES_NOT_SENT = FaultKind("plates_not_sent", "plates not sent", RETRIED)
TRACK_NOT_SENT = FaultKind("track_not_sent", "track not sent", RETRIED)
METRICS_NOT_SENT = FaultKind("metrics_not_sent", "metrics not sent", RETRIED)
PHOTOS_NOT_SENT = FaultKind("photos_not_sent", "photos not sent", RETRIED)
REFUSED_ITEMS = FaultKind("refused_items", "refused items")  # + count, measured
DATA_DROPPED = FaultKind("data_dropped", "data dropped")  # + count

# --- detection: alerts (cloud/alert_poll.py) -------------------------------------------------------------------
ALERT_LIST_FAILED = FaultKind("alert_list_failed", "alert list failed", RETRIED)
ALERT_LIST_INVALID = FaultKind("alert_list_invalid", "alert list invalid")

# --- detection: camera, position, clock, SD card ----------------------------------------------------------------
FRAME_LOOP_FAILED = FaultKind("frame_loop_failed", "frame loop error", RETRIED)
GPS_NOT_CONFIGURED = FaultKind("gps_not_configured", "GPS not configured")
GPS_SILENT = FaultKind("gps_silent", "GPS module silent")
CLOCK_WRONG = FaultKind("clock_wrong", "clock wrong by")  # + "12s"
SD_LOW = FaultKind("sd_low", "SD card low")  # + "800MB"

# --- collection (collection/indicators.py) ----------------------------------------------------------------------
CAMERA_ERROR = FaultKind("camera_error", "camera error")
DROPPED_FRAMES = FaultKind("dropped_frames", "dropped frames")  # + count
USB_ERROR = FaultKind("usb_error", "USB error")

SYSTEM = (UNDERVOLTAGE, THROTTLED, CPU_HOT)
DETECTION = (NO_CONFIG, CONFIG_REFUSED, CONFIG_POLL_FAILED, NO_CREDENTIALS, SIGN_IN_REFUSED, TOKEN_REFUSED,
             NOT_DEVICE_TOKEN, DEVICE_NOT_FOUND, NO_OWNER, NO_MODELS, MODEL_NOT_PUBLISHED, MODELS_NOT_UPDATED,
             MODEL_LOAD_FAILED, PLATES_NOT_SENT, TRACK_NOT_SENT, METRICS_NOT_SENT, PHOTOS_NOT_SENT, REFUSED_ITEMS,
             DATA_DROPPED, ALERT_LIST_FAILED, ALERT_LIST_INVALID, FRAME_LOOP_FAILED, GPS_NOT_CONFIGURED, GPS_SILENT,
             CLOCK_WRONG, SD_LOW)
COLLECTION = (CAMERA_ERROR, DROPPED_FRAMES, USB_ERROR)
ALL = SYSTEM + DETECTION + COLLECTION

CPU_HOT_C = 80.0  # the Pi 5 throttles from 85 °C: time to cool it before frames get slower


def system_faults(power: dict | None, temp_c: float | None) -> list[Fault]:
    """The faults of the Pi itself, from system_info.power_flags() and cpu_temp_c()."""
    power = power or {}
    faults = []
    if power.get("undervoltage_now"):
        faults.append(UNDERVOLTAGE.fault())
    if power.get("throttled_now"):
        faults.append(THROTTLED.fault())
    if temp_c is not None and temp_c >= CPU_HOT_C:
        faults.append(CPU_HOT.fault(f"{temp_c:.0f}C"))
    return faults
