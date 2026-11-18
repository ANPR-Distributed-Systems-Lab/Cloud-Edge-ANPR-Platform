package com.anpr.operations.messaging.edge;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

/**
 * Body of a "detection" edge event: the request of the device, validated by the ingest Lambda
 * (docs/api/ingest-detections.md). Only the fields this service stores are read; the rest is ignored.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
record DetectionBatchMessage(UUID batchId, List<Item> detections) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    record Item(UUID detectionId, OffsetDateTime detectedAt, String plate, Double ocrConfidence,
                Double detectorConfidence, String imageKey, Location location) {
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    record Location(Double lat, Double lon) {
    }
}
