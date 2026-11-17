from datetime import UTC, datetime

from detection.contract.metrics import DeviceMetric, FixType, GpsState, MetricsBatch, QueueLengths

RECORDED = datetime(2026, 11, 13, 4, 0, 0, 123_000, tzinfo=UTC)


def metric(**override):
    values = dict(recorded_at=RECORDED, cpu_temperature_c=54.04, cpu_usage_percent=31.26, ram_usage_percent=22.0,
                  processing_fps=1.7349, queues=QueueLengths(3, 10, 1), disk_free_mb=12_000, uptime_seconds=3600,
                  gps=GpsState(FixType.FIX_3D, 13))
    return DeviceMetric(**(values | override))


def test_a_measurement_has_the_contract_fields():
    assert metric().to_document() == {
        "recordedAt": "2026-11-13T04:00:00.123Z", "cpuTemperatureC": 54.0, "cpuUsagePercent": 31.3,
        "ramUsagePercent": 22.0, "processingFps": 1.73,
        "queues": {"detectionsPending": 3, "locationsPending": 10, "imagesPending": 1},
        "diskFreeMb": 12_000, "uptimeSeconds": 3600, "gps": {"fix": "FIX_3D", "satellites": 13}}


def test_values_outside_the_ranges_of_the_contract_are_brought_into_them():
    document = metric(cpu_temperature_c=300, cpu_usage_percent=-1, ram_usage_percent=140, processing_fps=-0.2,
                      disk_free_mb=-5, uptime_seconds=-1, gps=GpsState(FixType.NONE, 400)).to_document()
    assert document["cpuTemperatureC"] == 125.0 and document["cpuUsagePercent"] == 0.0
    assert document["ramUsagePercent"] == 100.0 and document["processingFps"] == 0.0
    assert document["diskFreeMb"] == 0 and document["uptimeSeconds"] == 0
    assert document["gps"] == {"fix": "NONE", "satellites": 100}


def test_measurements_read_back_and_a_batch_has_a_stable_trace_id():
    document = metric().to_document()
    assert DeviceMetric.from_document(document).to_document() == document
    batch = MetricsBatch((metric(),))
    assert batch.to_document() == {"metrics": [document]}
    assert batch.trace_id == MetricsBatch((metric(),)).trace_id
