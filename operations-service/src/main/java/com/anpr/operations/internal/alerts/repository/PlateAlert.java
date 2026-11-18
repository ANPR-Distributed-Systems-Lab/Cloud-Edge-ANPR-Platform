package com.anpr.operations.internal.alerts.repository;

import java.util.UUID;

/** The alert of one plate, read without the rest of the alert. */
public interface PlateAlert {
    String getPlate();

    UUID getAlertId();
}
