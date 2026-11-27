package com.anpr.operations.internal.radial.model;

import com.anpr.operations.shared.time.TimeRange;

/** What the user asks View 2: a circle on the map and a time range. Both ends of the range are required. */
public record RadialQuery(double lat, double lon, int radiusMeters, TimeRange period, int trackIntervalSeconds) {
}
