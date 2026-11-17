package com.anpr.devicemanagement.internal.images;

import lombok.AccessLevel;
import lombok.NoArgsConstructor;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.UUID;

/**
 * The S3 key layout of photos, {@code images/{deviceId}/{yyyy}/{MM}/{dd}/{frameId}.jpg} with the UTC date of capture
 * (docs/api/ingest-detections.md). The ingest Lambda checks the same layout and the device computes it
 * (rpi-edge/detection/contract/images.py), so it is a contract, not configuration.
 */
@NoArgsConstructor(access = AccessLevel.PRIVATE)
final class ImageKeys {
    private static final DateTimeFormatter DATE_PATH = DateTimeFormatter.ofPattern("yyyy/MM/dd").withZone(ZoneOffset.UTC);

    static String of(UUID deviceId, Frame frame) {
        return "images/" + deviceId + "/" + DATE_PATH.format(frame.capturedAt()) + "/" + frame.frameId() + ".jpg";
    }
}
