package com.anpr.devicemanagement.internal.overview;

import com.anpr.devicemanagement.internal.configuration.ConfigurationService;
import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.devices.DeviceLookup;
import com.anpr.devicemanagement.internal.metrics.Measurement;
import com.anpr.devicemanagement.internal.metrics.MetricsService;
import com.anpr.devicemanagement.shared.security.Caller;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;

/** The device of the caller with its online state, combined from the registry, the metrics and the configuration. */
@Service
@RequiredArgsConstructor
public class DeviceOverviewService {
    private final DeviceLookup deviceLookup;
    private final MetricsService metrics;
    private final ConfigurationService configurations;
    private final OverviewProperties properties;
    private final Clock clock;

    public DeviceOverview overviewOf(Caller caller) {
        Device device = deviceLookup.deviceOf(caller);
        Instant lastMetricsAt = metrics.lastMeasurement(device.getDeviceId()).map(Measurement::getRecordedAt).orElse(null);
        return new DeviceOverview(device, lastMetricsAt, isOnline(device, lastMetricsAt));
    }

    /** Uses the metrics interval the device is configured with; a change reaches the device only at its next poll. */
    private boolean isOnline(Device device, Instant lastMetricsAt) {
        if (lastMetricsAt == null) {
            return false;
        }
        int metricsSeconds = configurations.get(device.getDeviceId()).getSettings().getIntervals().getMetricsSeconds();
        Duration threshold = Duration.ofSeconds((long) metricsSeconds * properties.onlineWithinMetricsIntervals());
        return lastMetricsAt.isAfter(clock.instant().minus(threshold));
    }
}
