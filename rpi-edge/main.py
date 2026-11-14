"""Entry point of the container: runs the mode chosen by EDGE_MODE (rpi-edge/.env, see README.md).

  collection  records full-resolution frames for training (DATA_COLLECTION.md)
  detection   reads plates and sends them to the cloud (DETECTION.md)
"""
import os
import sys

from common.jsonlog import log

MODES = ("collection", "detection")


def main() -> None:
    mode = os.environ.get("EDGE_MODE") or "collection"
    if mode not in MODES:
        log("unknown_mode", level="error", mode=mode, allowed=MODES)
        sys.exit(2)
    log("mode_selected", mode=mode)
    if mode == "collection":
        from collection.main import main as run
    else:
        from detection.main import main as run
    run()


if __name__ == "__main__":
    main()
