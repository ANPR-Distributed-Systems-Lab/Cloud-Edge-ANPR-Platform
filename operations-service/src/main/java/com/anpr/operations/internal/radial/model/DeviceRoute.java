package com.anpr.operations.internal.radial.model;

import com.anpr.operations.internal.locations.repository.LocationPoint;

import java.util.List;
import java.util.UUID;

/** Route of one device in the time range, oldest point first. */
public record DeviceRoute(UUID deviceId, List<LocationPoint> points, boolean truncated) {
}
