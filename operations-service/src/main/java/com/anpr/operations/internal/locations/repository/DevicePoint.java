package com.anpr.operations.internal.locations.repository;

import java.util.UUID;

/** A route point together with its device: View 2 reads the routes of several devices in one query. */
public interface DevicePoint extends LocationPoint {
    UUID getDeviceId();
}
