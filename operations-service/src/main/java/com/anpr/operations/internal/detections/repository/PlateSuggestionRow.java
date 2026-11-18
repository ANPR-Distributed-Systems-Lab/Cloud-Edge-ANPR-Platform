package com.anpr.operations.internal.detections.repository;

import java.time.OffsetDateTime;

public interface PlateSuggestionRow {
    String getPlate();

    OffsetDateTime getLastDetectedAt();
}