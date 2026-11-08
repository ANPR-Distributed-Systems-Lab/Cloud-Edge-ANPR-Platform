package com.anpr.operations.internal.detections.model;

import java.time.OffsetDateTime;

public record DetectionFilter(
        String plate,
        OffsetDateTime from,
        OffsetDateTime to)
{}
