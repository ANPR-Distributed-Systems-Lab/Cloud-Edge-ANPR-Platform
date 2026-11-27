-- D17: lastDetectedAt of an alert is computed when reading, from the detections of its plate (Alert, @Formula).
-- The stored column was never written, and the index built on it ordered nothing.
DROP INDEX idx_alerts_account_detected;

ALTER TABLE alerts DROP COLUMN last_detected_at;
