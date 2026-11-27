package com.anpr.operations.internal.radial.model;

import com.anpr.operations.internal.detections.model.DetectionWithAlert;

import java.util.List;

/** View 2 result: detections inside the circle, oldest first, and the routes of the devices in the same time range. */
public record RadialAnalysis(double centerLat, double centerLon, int radiusMeters,
                             List<DetectionWithAlert> detections, boolean truncated, List<DeviceRoute> routes) {
}
