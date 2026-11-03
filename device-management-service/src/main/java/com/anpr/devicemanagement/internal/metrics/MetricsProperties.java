package com.anpr.devicemanagement.internal.metrics;

import jakarta.validation.constraints.NotNull;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

import java.time.Duration;

/**
 * @param retention    how long measurements are kept; older ones are refused and expire from the table
 * @param maxClockSkew how far in the future a recordedAt may be (clock of the device ahead of ours)
 */
@Validated
@ConfigurationProperties(prefix = "app.metrics")
public record MetricsProperties(@NotNull Duration retention, @NotNull Duration maxClockSkew) {
}
