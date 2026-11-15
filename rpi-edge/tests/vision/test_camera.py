"""Camera on stand-ins for picamera2 and libcamera: which controls each setting becomes, and when a change needs a
restart. The real modules exist only on the Pi, so the stand-ins record what the camera is told."""
import sys
import types
from enum import Enum

import numpy as np
import pytest
from samples import configuration

from detection.contract.configuration import MAX_EXPOSURE_US
from detection.vision.camera import Camera


class AwbMode(Enum):
    Auto = 0
    Daylight = 1
    Cloudy = 2
    Tungsten = 3
    Fluorescent = 4
    Indoor = 5


class FakeRequest:
    def __init__(self, image, metadata):
        self.image, self.metadata, self.released = image, metadata, False

    def make_array(self, name):
        return self.image

    def get_metadata(self):
        return self.metadata

    def release(self):
        self.released = True


class FakePicamera2:
    instances: list["FakePicamera2"] = []

    def __init__(self):
        self.video_config = None
        self.controls_sent: list[dict] = []
        self.started = self.closed = False
        self.camera_controls = {"AnalogueGain": (1.0, 22.26, 1.0)}
        self.image = np.full((100, 100, 3), 30, np.uint8)  # dark: the automatic modes want more light
        self.metadata = {"ExposureTime": 500, "AnalogueGain": 1.0, "DigitalGain": 1.0}
        FakePicamera2.instances.append(self)

    def create_video_configuration(self, **config):
        self.video_config = config
        return dict(config)

    def configure(self, config):
        pass

    def start(self):
        self.started = True

    def set_controls(self, controls):
        self.controls_sent.append(controls)

    def capture_request(self):
        return FakeRequest(self.image, self.metadata)

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def fake_camera_stack(monkeypatch):
    FakePicamera2.instances = []
    libcamera = types.ModuleType("libcamera")
    libcamera.Transform = lambda hflip, vflip: ("transform", hflip, vflip)
    libcamera.ColorSpace = types.SimpleNamespace(Sycc=lambda: "sycc")
    libcamera.controls = types.SimpleNamespace(AwbModeEnum=AwbMode)
    picamera2 = types.ModuleType("picamera2")
    picamera2.Picamera2 = FakePicamera2
    monkeypatch.setitem(sys.modules, "libcamera", libcamera)
    monkeypatch.setitem(sys.modules, "picamera2", picamera2)


def camera_settings(**camera):
    return configuration(camera=camera).camera


def opened(**camera) -> tuple[Camera, FakePicamera2]:
    cam = Camera()
    cam.open(camera_settings(**camera))
    return cam, FakePicamera2.instances[-1]


def test_the_camera_opens_with_the_flips_and_a_sensor_rate_of_at_least_10_fps():
    _, picam = opened(fps=3.0, hflip=True, vflip=False)
    assert picam.video_config["transform"] == ("transform", True, False)
    assert picam.video_config["main"]["size"] == (4056, 3040) and picam.started
    assert picam.video_config["controls"]["FrameDurationLimits"] == (100_000, 100_000)  # 10 fps, not 3
    _, picam = opened(fps=11.7)
    assert picam.video_config["controls"]["FrameDurationLimits"] == (85_470, 85_470)


@pytest.mark.parametrize("mode, fixed", [
    ("MANUAL", {"ExposureTime": 500, "AnalogueGain": 2.0}),
    ("AUTO_GAIN", {"ExposureTime": 500}),  # exposure fixed, gain left to the software auto exposure
    ("AUTO_EXPOSURE", {"AnalogueGain": 2.0}),
    ("AUTO", {}),
])
def test_each_exposure_mode_fixes_only_its_own_controls(mode, fixed):
    _, picam = opened(exposure={"mode": mode})
    controls = picam.video_config["controls"]
    assert controls["AeEnable"] is False  # libcamera's AGC never runs: it cannot be capped
    assert {k: controls[k] for k in ("ExposureTime", "AnalogueGain") if k in controls} == fixed


@pytest.mark.parametrize("mode, enum", [("AUTO", AwbMode.Auto), ("DAYLIGHT", AwbMode.Daylight),
                                        ("CLOUDY", AwbMode.Cloudy), ("TUNGSTEN", AwbMode.Tungsten),
                                        ("FLUORESCENT", AwbMode.Fluorescent), ("INDOOR", AwbMode.Indoor)])
def test_every_white_balance_preset_maps_to_a_libcamera_mode(mode, enum):
    _, picam = opened(whiteBalance={"mode": mode})
    assert picam.video_config["controls"]["AwbEnable"] is True
    assert picam.video_config["controls"]["AwbMode"] is enum


def test_a_manual_white_balance_uses_the_gains():
    _, picam = opened(whiteBalance={"mode": "MANUAL", "redGain": 1.8, "blueGain": 1.5})
    assert picam.video_config["controls"]["AwbEnable"] is False
    assert picam.video_config["controls"]["ColourGains"] == (1.8, 1.5)


def test_the_same_settings_change_nothing():
    cam, picam = opened()
    cam.apply(camera_settings())
    assert picam.controls_sent == [] and len(FakePicamera2.instances) == 1


def test_exposure_white_balance_and_a_rate_below_10_fps_change_live():
    cam, picam = opened(fps=3.0)
    cam.apply(camera_settings(fps=5.0, exposure={"mode": "MANUAL", "exposureUs": 800, "gain": 3.0},
                              whiteBalance={"mode": "CLOUDY"}))
    assert len(FakePicamera2.instances) == 1  # no restart
    [controls] = picam.controls_sent
    assert controls["ExposureTime"] == 800 and controls["AnalogueGain"] == 3.0
    assert controls["AwbMode"] is AwbMode.Cloudy


@pytest.mark.parametrize("change", [{"hflip": False}, {"vflip": False}, {"fps": 11.7}])
def test_flips_and_a_new_sensor_rate_restart_the_camera(change):
    cam, first = opened(fps=3.0, hflip=True, vflip=True)
    cam.apply(camera_settings(**{"fps": 3.0, "hflip": True, "vflip": True} | change))
    assert first.closed and len(FakePicamera2.instances) == 2
    second = FakePicamera2.instances[-1]
    expected = ("transform", change.get("hflip", True), change.get("vflip", True))
    assert second.video_config["transform"] == expected and second.started


def test_the_automatic_exposure_never_goes_past_the_configured_limits():
    cam, picam = opened(exposure={"mode": "AUTO", "maxExposureUs": 540, "maxGain": 4.0, "targetBrightness": 0.4})
    picam.image[:] = 2  # almost black: the correction asks for far more light than the limits allow
    for _ in range(20):
        frame = cam.capture()
        if picam.controls_sent:
            picam.metadata = {"ExposureTime": picam.controls_sent[-1]["ExposureTime"],
                              "AnalogueGain": picam.controls_sent[-1]["AnalogueGain"], "DigitalGain": 1.0}
    last = picam.controls_sent[-1]
    assert last["ExposureTime"] == 540 and last["AnalogueGain"] == pytest.approx(4.0)
    assert frame.image.shape == (100, 100, 3)


def test_auto_gain_keeps_the_configured_exposure_time():
    cam, picam = opened(exposure={"mode": "AUTO_GAIN", "exposureUs": 300, "maxGain": 6.0})
    cam.capture()
    assert picam.controls_sent[-1]["ExposureTime"] == 300 and picam.controls_sent[-1]["AnalogueGain"] > 1.0


def test_manual_exposure_is_left_alone_after_a_capture():
    cam, picam = opened(exposure={"mode": "MANUAL"})
    cam.capture()
    assert picam.controls_sent == []


def test_the_longest_exposure_the_contract_allows_fits_into_a_frame_at_every_rate():
    cam, _ = opened(fps=11.7)  # the highest camera.fps, the shortest frame
    assert cam._limits()[1] >= MAX_EXPOSURE_US
