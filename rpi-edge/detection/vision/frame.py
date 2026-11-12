from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass(frozen=True)
class Frame:
    image: np.ndarray  # BGR, full resolution
    captured_at: datetime  # UTC

    @property
    def size(self) -> tuple[int, int]:
        """(width, height)"""
        height, width = self.image.shape[:2]
        return width, height
