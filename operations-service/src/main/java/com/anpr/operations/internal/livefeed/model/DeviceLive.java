package com.anpr.operations.internal.livefeed.model;

import com.anpr.operations.internal.locations.repository.LocationPoint;

import java.util.List;
import java.util.UUID;

/** The latest known position of a device and its route from the time window, oldest point first. */
public record DeviceLive(UUID deviceId, LocationPoint lastLocation, List<LocationPoint> track) {
}
