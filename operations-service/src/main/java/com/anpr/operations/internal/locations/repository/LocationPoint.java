package com.anpr.operations.internal.locations.repository;

import java.time.Instant;

/**
 * Time and position of one device location, read without its ids: all a route on the map needs. Read by native
 * queries, so plain types: timestamptz comes as Instant and the position as two numbers (WGS 84 degrees).
 */
public interface LocationPoint {
    Instant getRecordedAt();

    double getLat();

    double getLon();
}
