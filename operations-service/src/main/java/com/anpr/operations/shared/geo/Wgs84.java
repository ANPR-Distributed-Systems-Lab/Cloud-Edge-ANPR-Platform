package com.anpr.operations.shared.geo;

import lombok.NoArgsConstructor;
import org.locationtech.jts.geom.Coordinate;
import org.locationtech.jts.geom.GeometryFactory;
import org.locationtech.jts.geom.Point;
import org.locationtech.jts.geom.PrecisionModel;

import static lombok.AccessLevel.PRIVATE;

/** Builds GPS points (WGS84, SRID 4326) for the geography columns. Shared by detections and device locations. */
@NoArgsConstructor(access = PRIVATE)
public final class Wgs84 {
    public static final int SRID = 4326;

    // GeometryFactory is immutable and thread-safe, so one instance serves the whole application.
    private static final GeometryFactory FACTORY = new GeometryFactory(new PrecisionModel(), SRID);

    /** JTS takes x then y, so the longitude goes first; this method takes them in the usual lat, lon order. */
    public static Point point(double lat, double lon) {
        return FACTORY.createPoint(new Coordinate(lon, lat));
    }
}
