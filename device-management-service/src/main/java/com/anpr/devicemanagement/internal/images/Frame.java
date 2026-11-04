package com.anpr.devicemanagement.internal.images;

import java.time.Instant;
import java.util.UUID;

/** A frame whose photo the device is about to upload. */
public record Frame(UUID frameId, Instant capturedAt) {
}
