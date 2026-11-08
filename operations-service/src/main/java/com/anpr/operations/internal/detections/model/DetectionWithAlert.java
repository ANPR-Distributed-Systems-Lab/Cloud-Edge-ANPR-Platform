package com.anpr.operations.internal.detections.model;

import java.util.UUID;

public record DetectionWithAlert(Detection detection, UUID alertId) {
}