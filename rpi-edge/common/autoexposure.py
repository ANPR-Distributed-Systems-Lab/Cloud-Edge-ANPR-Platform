"""Software auto exposure with hard limits.

libcamera's own AGC cannot be told "never expose longer than X", so exposure is driven from here:
the camera runs fully manual and this module picks the next (exposure time, gain) pair from the
brightness of the previous frame.
"""

GAMMA = 2.2  # frames are gamma encoded, exposure scales light linearly
STEP = 0.85  # fraction of the needed correction applied per update. The correction is computed from the exposure
# that actually produced the measured frame, so control latency does not compound and little damping is needed
MAX_RATIO = 4.0  # largest correction per update (the measurement is not linear near black and near clipping)
DEADBAND = 0.04  # ignore brightness errors smaller than this ratio


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def split_exposure(mode: str, total: float, s: dict, limits: tuple) -> tuple[float, float]:
    """Split a total exposure (exposure_us * gain) into (exposure_us, gain) according to the mode.

    limits = (min exposure_us, hardware max exposure_us, min gain, hardware max gain)
    """
    t_min, t_hw_max, g_min, g_hw_max = limits
    t_max = _clamp(s["max_exposure_us"], t_min, t_hw_max)
    g_max = _clamp(s["max_gain"], g_min, g_hw_max)
    if mode == "auto_gain":  # exposure time is whatever the user fixed, gain does the balancing
        t = _clamp(s["exposure_us"], t_min, t_hw_max)
        g = _clamp(total / t, g_min, g_max)
    elif mode == "auto_exposure":  # gain is fixed, exposure time does the balancing up to its hard limit
        g = _clamp(s["gain"], g_min, g_hw_max)
        t = _clamp(total / g, t_min, t_max)
    else:  # "auto": exposure time first (up to its hard limit), gain only once the time is maxed out
        t = _clamp(total / g_min, t_min, t_max)
        g = _clamp(total / t, g_min, g_max)
    return t, g


def next_exposure(mode: str, brightness: float, t: float, g: float, s: dict, limits: tuple) -> tuple[float, float]:
    """Return the (exposure_us, gain) to use next, given the brightness (0..1) measured at (t, g)."""
    measured = max(brightness, 0.01) ** GAMMA
    wanted = s["target_brightness"] ** GAMMA
    ratio = _clamp(wanted / measured, 1 / MAX_RATIO, MAX_RATIO)
    if abs(ratio - 1) < DEADBAND:
        ratio = 1.0
    # Always re-split, even inside the deadband, so a lowered limit takes effect immediately.
    return split_exposure(mode, t * g * ratio**STEP, s, limits)
