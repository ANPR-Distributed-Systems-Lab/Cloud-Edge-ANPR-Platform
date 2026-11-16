"""The IMX477 at the one resolution both modes use: the frames of the training data and of the detector."""

FRAME_SIZE = (4056, 3040)  # (width, height), the full sensor
MAX_FPS = 11.7  # the fastest the sensor delivers 4056x3040 (rpicam-hello --list-cameras)
# The longest exposure either mode accepts. An exposure must end within 97 % of a sensor frame, and the sensor runs
# at 10 fps or faster in both modes (83 ms at 11.7 fps), so 80 ms always fits.
MAX_EXPOSURE_US = 80_000
