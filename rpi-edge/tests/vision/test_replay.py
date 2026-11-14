import cv2
import numpy as np
import pytest

from detection.vision.replay import ReplayCamera


def test_frames_come_in_name_order_and_loop(tmp_path):
    for folder, name, value in (("0001", "img_000002.jpg", 200), ("0000", "img_000001.jpg", 100),
                                ("0000", ".img_000003.part.jpg", 0)):
        (tmp_path / folder).mkdir(exist_ok=True)
        cv2.imwrite(str(tmp_path / folder / name), np.full((8, 8, 3), value, np.uint8))
    camera = ReplayCamera(tmp_path)
    camera.open({})
    values = [int(camera.capture().image.mean()) for _ in range(3)]
    assert values[0] == pytest.approx(100, abs=2) and values[1] == pytest.approx(200, abs=2)
    assert values[2] == values[0]  # starts again; the half-written file is never read


def test_an_empty_directory_is_refused(tmp_path):
    with pytest.raises(ValueError):
        ReplayCamera(tmp_path)
