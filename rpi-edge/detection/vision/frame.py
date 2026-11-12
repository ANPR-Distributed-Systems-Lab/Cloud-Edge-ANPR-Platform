from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass
class Frame:
    image: np.ndarray  # BGR, full resolution
    captured_at: datetime  # UTC
