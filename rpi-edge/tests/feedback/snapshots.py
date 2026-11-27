"""A Snapshot of a running device, to override per test."""
from dataclasses import replace

from detection.contract.configuration import ModelVersions
from detection.contract.metrics import FixType
from detection.feedback.screens import LastPlate, Snapshot, Stage, Waiting
from detection.gps.tracker import GpsStatus

FIX_3D = GpsStatus(receiving=True, fix=FixType.FIX_3D, satellites_used=13, satellites_in_view=18)
RUNNING = Snapshot(
    stage=Stage.RUNNING, fps=2.94, online=True, sign_in_failed=False, denied=False, gps=FIX_3D,
    fix_seconds_ago=0.4, fix_fresh=True, accuracy_m=4.5, speed_mps=12.5, waiting=Waiting(12, 340, 5), faults=(),
    ip="192.168.137.12", temp_c=52.4, config_version=12, models=ModelVersions("v3", "v3"), sd_free_mb=25_300,
    last_plates=(LastPlate("WA12345", 125.0, True), LastPlate("KR9876A", 15.0, False)), alert_list=5)


def snapshot(**override) -> Snapshot:
    return replace(RUNNING, **override)
