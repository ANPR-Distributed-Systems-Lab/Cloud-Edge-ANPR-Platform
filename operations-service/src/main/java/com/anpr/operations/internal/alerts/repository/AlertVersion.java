package com.anpr.operations.internal.alerts.repository;

import java.util.UUID;

/** Id and version of an alert, read without the rest of it: what the device list ETag is built from. */
public interface AlertVersion {
    UUID getAlertId();

    long getVersion();
}
