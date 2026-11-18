package com.anpr.operations.internal.devices;

import java.util.UUID;

/** Data of a device arrived before its owner is known; the message is retried and ends in the DLQ if it stays so. */
public class DeviceNotPairedException extends RuntimeException {
    public DeviceNotPairedException(UUID deviceId) {
        super("Device " + deviceId + " has no owner");
    }
}
