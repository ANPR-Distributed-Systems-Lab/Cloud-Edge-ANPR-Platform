CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE detections (
    detection_id        UUID PRIMARY KEY,
    account_id          UUID NOT NULL REFERENCES accounts (account_id),
    device_id           UUID NOT NULL REFERENCES devices (device_id),
    plate               VARCHAR(10) NOT NULL,
    detected_at         TIMESTAMPTZ NOT NULL,
    position            GEOGRAPHY(Point, 4326) NOT NULL,
    ocr_confidence      DOUBLE PRECISION NOT NULL,
    detector_confidence DOUBLE PRECISION NOT NULL,
    image_key           VARCHAR(255) NOT NULL
);

CREATE INDEX idx_detections_account_detected ON detections (account_id, detected_at DESC);
CREATE INDEX idx_detections_account_plate_detected ON detections (account_id, plate, detected_at DESC);
CREATE INDEX idx_detections_position ON detections USING GIST (position);

CREATE TABLE device_locations (
    location_id UUID PRIMARY KEY,
    account_id  UUID NOT NULL REFERENCES accounts (account_id),
    device_id   UUID NOT NULL REFERENCES devices (device_id),
    recorded_at TIMESTAMPTZ NOT NULL,
    position    GEOGRAPHY(Point, 4326) NOT NULL
);

CREATE INDEX idx_device_locations_account_recorded ON device_locations (account_id, recorded_at DESC);
