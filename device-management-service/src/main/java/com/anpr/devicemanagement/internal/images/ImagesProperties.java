package com.anpr.devicemanagement.internal.images;

import jakarta.validation.constraints.NotNull;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

import java.time.Duration;

/**
 * @param uploadUrlValidity how long a presigned upload URL may be used
 * @param maxCaptureAge     the oldest capturedAt accepted; the ingest Lambda refuses older detections anyway
 * @param maxClockSkew      how far in the future a capturedAt may be (clock of the device ahead of ours)
 */
@Validated
@ConfigurationProperties(prefix = "app.images")
public record ImagesProperties(@NotNull Duration uploadUrlValidity, @NotNull Duration maxCaptureAge,
                               @NotNull Duration maxClockSkew) {
}
