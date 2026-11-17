"""The faults of the detection mode (common/faults.py): those the threads report, and those read at each refresh.

  reported   no configuration, config refused, device not paired (cloud/config_poll.py); no models, model load
             failed, models not updated (cloud/model_updater.py); frame loop error (loop.py)
  read here  sign-in failed and access denied (the latest request, cloud/api.py); refused items (rows the
             platform refused since the mode started, kept in a quarantine of the queues for diagnosis); SD card low;
             power too low, CPU throttled, CPU hot
"""
from common.display import count
from common.faults import Fault, FaultBoard, system_faults
from detection.cloud.api import CloudHealth
from detection.delivery.queues import Queues

SD_LOW_FREE_MB = 1000  # the queues, the photos and the models live on the SD card


def quarantined(queues: Queues) -> int:
    return sum(q.quarantined() for q in (queues.detections, queues.locations, queues.metrics, queues.images))


def detection_faults(board: FaultBoard, health: CloudHealth, refused: int, sd_free_mb: int | None,
                     power: dict | None, temp_c: float | None) -> list[Fault]:
    """`refused`: rows quarantined since the mode started. Older ones stay in the quarantine for up to 30 days and
    cannot be cleared from the device, so counting them would keep the fault on long after anyone could act."""
    faults = board.active()
    if health.sign_in_failed:
        faults.append(Fault("sign_in", "sign-in failed"))
    if health.forbidden:
        faults.append(Fault("forbidden", "access denied (403)"))
    if refused > 0:
        faults.append(Fault("refused", f"refused items {count(refused)}"))
    if sd_free_mb is not None and sd_free_mb < SD_LOW_FREE_MB:
        faults.append(Fault("sd_low", f"SD card low {sd_free_mb}MB"))
    return faults + system_faults(power, temp_c)
