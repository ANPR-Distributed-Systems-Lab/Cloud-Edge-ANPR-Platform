package com.anpr.operations.internal.livefeed.model;

import com.anpr.operations.internal.locations.model.DeviceLocation;

import java.util.List;
import java.util.UUID;

/** The latest known position of a device and its route from the time window, oldest point first. */
public record DeviceLive(UUID deviceId, DeviceLocation lastLocation, List<DeviceLocation> track) {
}
