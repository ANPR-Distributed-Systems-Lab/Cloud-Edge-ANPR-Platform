package com.anpr.operations.internal.livefeed.model;

import com.anpr.operations.internal.detections.model.DetectionWithAlert;

import java.util.List;

/** One poll of the live feed (View 3). */
public record LiveFeed(List<DetectionWithAlert> detections, String nextCursor, boolean hasMore,
                       List<DeviceLive> devices) {
}
