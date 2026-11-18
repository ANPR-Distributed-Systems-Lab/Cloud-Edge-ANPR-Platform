package com.anpr.operations.internal.detections.model;

import com.anpr.operations.shared.time.TimeRange;

public record DetectionFilter(String plate, TimeRange period) {
}
