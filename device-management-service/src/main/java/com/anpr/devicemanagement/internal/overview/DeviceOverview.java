package com.anpr.devicemanagement.internal.overview;

import com.anpr.devicemanagement.internal.devices.Device;

import java.time.Instant;

/**
 * A device with its current state.
 *
 * @param lastMetricsAt recordedAt of its latest measurement within the retention, null if there is none
 * @param online        whether that measurement is recent enough (see {@link OverviewProperties})
 */
public record DeviceOverview(Device device, Instant lastMetricsAt, boolean online) {
}
