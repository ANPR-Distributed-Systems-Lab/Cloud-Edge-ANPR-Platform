package com.anpr.devicemanagement.internal.overview;

import jakarta.validation.constraints.Min;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/**
 * @param onlineWithinMetricsIntervals a device is online while its latest measurement is younger than this many of
 *                                     its metrics intervals; with 3, a device that missed two reports in a row is
 *                                     still online
 */
@Validated
@ConfigurationProperties(prefix = "app.overview")
public record OverviewProperties(@Min(1) int onlineWithinMetricsIntervals) {
}
