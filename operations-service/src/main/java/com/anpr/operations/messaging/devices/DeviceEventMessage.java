package com.anpr.operations.messaging.devices;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.time.Instant;
import java.util.UUID;

/**
 * Body of a device event (docs/events/device-events.md). Owned by device-management; changes are additive only,
 * so unknown fields are ignored. {@code accountId} is absent in {@code device.unpaired}.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
record DeviceEventMessage(UUID eventId, Instant occurredAt, Long version, UUID deviceId, UUID accountId) {
}
