"""The IMX477 through picamera2: full-resolution BGR frames for the detector, with the software auto exposure of
the collection mode (common.autoexposure), so both modes expose the same way for the same settings.

The sensor runs at SENSOR_MIN_FPS or faster, while the frame loop analyses at most camera.fps frames per second:
a capture then waits for the next sensor frame (queue=False) for a short time only, and the auto exposure gets
fresh measurements. picamera2 is imported when the camera opens, so the rest of the mode imports without it.
"""
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import numpy as np

from common import autoexposure
from common.jsonlog import log
from detection.config.schema import CameraSettings
from detection.vision.frame import Frame

SIZE = (4056, 3040)  # the recording resolution of the training frames
SENSOR_MIN_FPS = 10.0
BUFFERS = 3  # each holds a 37 MB BGR frame plus the raw sensor data
LUMA = np.array([0.114, 0.587, 0.299], dtype=np.float32)  # BT.601 weights in B, G, R order
METER_STEP = 8  # every 8th pixel of the metered area is enough for its mean brightness
MIN_EXPOSURE_US = 30.0
MIN_GAIN = 1.0
FALLBACK_MAX_GAIN = 16.0  # when the camera does not report its limit
EXPOSURE_SHARE_OF_FRAME = 0.97  # the exposure must end before the next frame starts
MIN_EXPOSURE_CHANGE_US = 0.5  # smaller corrections are not worth a control update
MIN_GAIN_CHANGE = 0.002
MAX_SENSOR_AGE_NS = 10**10  # a sensor timestamp older than 10 s is not trusted for the capture time


class Camera:
    def __init__(self) -> None:
        self.picam2 = None
        self._settings: CameraSettings | None = None
        self._sensor_fps = SENSOR_MIN_FPS

    @property
    def is_open(self) -> bool:
        return self.picam2 is not None

    def open(self, camera: CameraSettings) -> None:
        from libcamera import ColorSpace, Transform
        from picamera2 import Picamera2

        self.picam2 = Picamera2()
        self._sensor_fps = _sensor_fps(camera)
        config = self.picam2.create_video_configuration(
            main={"size": SIZE, "format": "RGB888"},  # picamera2's RGB888 is B, G, R in memory: OpenCV order
            controls=self._controls(camera),
            transform=Transform(hflip=camera.hflip, vflip=camera.vflip),
            buffer_count=BUFFERS,
            queue=False,  # a capture returns a frame taken after the call, never an old queued one
        )
        # The colour space the collection mode records the training frames with (sRGB transfer, full range);
        # the video default for RGB would be Rec709.
        config["colour_space"] = ColorSpace.Sycc()
        self.picam2.configure(config)
        self.picam2.start()
        self._settings = camera
        log("camera_started", size=list(SIZE), sensor_fps=self._sensor_fps, hflip=camera.hflip, vflip=camera.vflip,
            exposure_mode=camera.exposure.mode)

    def apply(self, camera: CameraSettings) -> None:
        """New settings: controls change live, flips and the sensor rate need a restart of the camera."""
        if camera == self._settings:
            return
        if self._needs_restart(camera):
            self.close()
            self.open(camera)
            return
        self.picam2.set_controls(self._controls(camera))
        self._settings = camera
        log("camera_settings_applied", exposure_mode=camera.exposure.mode)

    def _needs_restart(self, camera: CameraSettings) -> bool:
        flips_changed = (camera.hflip, camera.vflip) != (self._settings.hflip, self._settings.vflip)
        return flips_changed or _sensor_fps(camera) != self._sensor_fps

    def _controls(self, camera: CameraSettings) -> dict:
        from libcamera import controls as lc

        ex, wb = camera.exposure, camera.white_balance
        duration = int(1_000_000 / self._sensor_fps)
        controls = {"AeEnable": False, "FrameDurationLimits": (duration, duration)}
        if ex.mode in ("MANUAL", "AUTO_GAIN"):
            controls["ExposureTime"] = ex.exposure_us
        if ex.mode in ("MANUAL", "AUTO_EXPOSURE"):
            controls["AnalogueGain"] = ex.gain
        if wb.mode == "MANUAL":
            controls.update(AwbEnable=False, ColourGains=(wb.red_gain, wb.blue_gain))
        else:
            controls.update(AwbEnable=True, AwbMode=getattr(lc.AwbModeEnum, wb.mode.capitalize()))
        return controls

    def capture(self) -> Frame:
        request = self.picam2.capture_request()
        try:
            image = request.make_array("main")  # a copy, the buffer goes straight back to the camera
            metadata = request.get_metadata()
        finally:
            request.release()
        self._auto_expose(image, metadata)
        return Frame(image, _capture_time(metadata))

    def _auto_expose(self, image: np.ndarray, metadata: dict) -> None:
        ex = self._settings.exposure
        if ex.mode == "MANUAL":
            return
        t = metadata.get("ExposureTime", ex.exposure_us)
        g = metadata.get("AnalogueGain", 1.0) * metadata.get("DigitalGain", 1.0)
        t_new, g_new = autoexposure.next_exposure(ex.mode.lower(), _brightness(image), t, g, asdict(ex), self._limits())
        if abs(t_new - t) > MIN_EXPOSURE_CHANGE_US or abs(g_new - g) > MIN_GAIN_CHANGE:
            self.picam2.set_controls({"ExposureTime": int(t_new), "AnalogueGain": float(g_new)})

    def _limits(self) -> tuple:
        """(min exposure us, max exposure us at the sensor rate, min gain, max analogue gain)."""
        try:
            max_gain = float(self.picam2.camera_controls["AnalogueGain"][1])
        except (KeyError, TypeError, IndexError):
            max_gain = FALLBACK_MAX_GAIN
        return MIN_EXPOSURE_US, 1_000_000 / self._sensor_fps * EXPOSURE_SHARE_OF_FRAME, MIN_GAIN, max_gain

    def close(self) -> None:
        if self.picam2 is not None:
            try:
                self.picam2.stop()
                self.picam2.close()
            except Exception as e:  # shutting down anyway
                log("camera_close_error", level="warning", error=repr(e))
            self.picam2 = None


def _sensor_fps(camera: CameraSettings) -> float:
    return max(SENSOR_MIN_FPS, camera.fps)


def _brightness(image: np.ndarray) -> float:
    """Mean luma (0..1) of the central 60 %, the metered area of the collection mode."""
    h, w = image.shape[:2]
    centre = image[h // 5: h * 4 // 5: METER_STEP, w // 5: w * 4 // 5: METER_STEP]
    return float((centre.astype(np.float32) @ LUMA).mean()) / 255.0


def _capture_time(metadata: dict) -> datetime:
    """Wall-clock time of the exposure, from the sensor timestamp (boot clock) rather than the time of return."""
    now = datetime.now(timezone.utc)
    sensor_ns = metadata.get("SensorTimestamp")
    if not sensor_ns or not hasattr(time, "CLOCK_BOOTTIME"):
        return now
    age_ns = time.clock_gettime_ns(time.CLOCK_BOOTTIME) - sensor_ns
    return now - timedelta(microseconds=age_ns / 1000) if 0 <= age_ns < MAX_SENSOR_AGE_NS else now
