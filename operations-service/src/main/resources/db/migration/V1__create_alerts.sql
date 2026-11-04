CREATE TABLE alerts (
    alert_id UUID PRIMARY KEY,
    account_id UUID NOT NULL,
    plate VARCHAR(10) NOT NULL,
    alert_text VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL,
    last_detected_at TIMESTAMPTZ,
    version BIGINT NOT NULL DEFAULT 0,
    CONSTRAINT uq_alerts_account_plate UNIQUE (account_id, plate)
);

CREATE INDEX idx_alerts_account_created ON alerts (account_id, created_at DESC);

CREATE INDEX idx_alerts_account_detected ON alerts (account_id, last_detected_at DESC);