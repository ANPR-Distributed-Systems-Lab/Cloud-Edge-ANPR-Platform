from datetime import UTC, datetime

from detection.contract.locations import Location, LocationBatch, LocationPoint

RECORDED = datetime(2026, 10, 30, 9, 14, 21, tzinfo=UTC)
ID = "0192f3a4-9a11-7d20-9c01-3b5d7f9a1c02"


def point(**override):
    values = dict(location_id=ID, recorded_at=RECORDED, lat=52.2296756, lon=21.0122287, accuracy_m=4.54,
                  speed_mps=13.9123, heading_deg=87.04)
    return LocationPoint(**(values | override))


def test_a_detection_location_is_rounded_and_reads_back():
    location = Location(52.2296756, 21.0122287, 4.54, 300)
    document = location.to_document()
    assert document == {"lat": 52.229676, "lon": 21.012229, "accuracyM": 4.5, "fixAgeMs": 300}
    assert Location.from_document(document).fix_age_ms == 300


def test_a_location_without_accuracy_omits_it():
    assert "accuracyM" not in Location(1.0, 2.0, None, 0).to_document()


def test_a_point_has_the_contract_fields():
    assert point().to_document() == {"locationId": ID, "recordedAt": "2026-10-30T09:14:21.000Z", "lat": 52.229676,
                                     "lon": 21.012229, "accuracyM": 4.5, "speedMps": 13.91, "headingDeg": 87.0}


def test_a_stationary_point_has_no_heading_and_a_heading_never_reaches_360():
    stationary = point(speed_mps=0.0, heading_deg=None).to_document()
    assert "headingDeg" not in stationary and stationary["speedMps"] == 0.0
    assert point(heading_deg=359.97).to_document()["headingDeg"] == 0.0


def test_points_read_back_and_a_batch_id_is_stable():
    document = point().to_document()
    assert LocationPoint.from_document(document).to_document() == document
    batch = LocationBatch((point(), point(location_id="0192f3a4-9a11-7d21-8b12-4c6e8a0b2d03")))
    assert batch.batch_id == LocationBatch(batch.points).batch_id
    assert batch.to_document()["batchId"] == batch.trace_id
    assert len(batch.to_document()["locations"]) == 2
