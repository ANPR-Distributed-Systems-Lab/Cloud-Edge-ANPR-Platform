CREATE TABLE accounts (
    account_id UUID PRIMARY KEY
);

CREATE TABLE devices (
    device_id UUID PRIMARY KEY,
    account_id UUID REFERENCES accounts (account_id),
    version BIGINT NOT NULL,

    CONSTRAINT uq_devices_account UNIQUE (account_id)
);
