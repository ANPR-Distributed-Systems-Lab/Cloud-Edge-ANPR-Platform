-- View 3 (live feed) follows the order in which detections were stored, not detected_at: detections buffered
-- offline on a device arrive late with an old detected_at, and a cursor over detected_at would skip them.
-- now() is the start of the storing transaction, so all detections of one batch share the same value.
ALTER TABLE detections ADD COLUMN ingested_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX idx_detections_account_ingested ON detections (account_id, ingested_at, detection_id);