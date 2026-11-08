package com.anpr.operations.internal.devices;

import com.anpr.operations.internal.devices.repository.DeviceRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.UUID;

/** The owner of a device, for data the device sends (detections, locations). */
@Component
@RequiredArgsConstructor
public class DeviceOwners {
    private final DeviceRepository deviceRepository;

    public UUID require(UUID deviceId) {
        return deviceRepository.findOwnerById(deviceId)
                .orElseThrow(() -> new DeviceNotPairedException(deviceId));
    }
}
