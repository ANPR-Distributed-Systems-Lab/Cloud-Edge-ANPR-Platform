-- Plate suggestions search by prefix (plate LIKE 'WA1%'). A B-Tree compared by the database collation cannot serve
-- a prefix LIKE, so the query read every detection of the account. varchar_pattern_ops compares character by
-- character, which turns the prefix into an index range ('WA1' <= plate < 'WA2'). Exact plate lookups (View 1 search,
-- lastDetectedAt of alerts) still use the index. Replaced under the same name instead of adding a second index.
DROP INDEX idx_detections_account_plate_detected;

CREATE INDEX idx_detections_account_plate_detected
    ON detections (account_id, plate varchar_pattern_ops, detected_at DESC);
