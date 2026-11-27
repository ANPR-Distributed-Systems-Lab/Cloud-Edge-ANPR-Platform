package com.anpr.operations.messaging.edge;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

/** Body of a "device-location" edge event (docs/api/ingest-device-locations.md). Speed and heading are not stored. */
@JsonIgnoreProperties(ignoreUnknown = true)
record LocationBatchMessage(UUID batchId, List<Item> locations) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    record Item(UUID locationId, OffsetDateTime recordedAt, Double lat, Double lon) {
    }
}
