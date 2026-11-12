package com.anpr.operations.internal.locations;

import com.anpr.operations.internal.devices.DevicePairingService;
import com.anpr.operations.internal.locations.model.DeviceLocation;
import com.anpr.operations.internal.locations.repository.DeviceLocationRepository;
import com.anpr.operations.shared.geo.Wgs84;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class DeviceLocationService {
    private final DeviceLocationRepository deviceLocationRepository;
    private final DevicePairingService pairingService;

    /** A GPS point as the device reported it, before the owner is known. */
    public record NewDeviceLocation(UUID locationId, OffsetDateTime recordedAt, double lat, double lon) {
    }

    /** Stores a batch of one device in one transaction. */
    @Transactional
    public void store(UUID deviceId, List<NewDeviceLocation> locations) {
        UUID ownerId = pairingService.requireOwner(deviceId);
        int inserted = 0;
        for (NewDeviceLocation l : locations) {
            inserted += deviceLocationRepository.insertIfAbsent(DeviceLocation.create(
                    l.locationId(), ownerId, deviceId, l.recordedAt(), Wgs84.point(l.lat(), l.lon())));
        }
        log.debug("Stored {} new of {} locations of device {}", inserted, locations.size(), deviceId);
    }

    /** Route of a device since the given time, oldest point first. */
    public List<DeviceLocation> track(UUID accountId, UUID deviceId, OffsetDateTime since) {
        return deviceLocationRepository.findTrack(accountId, deviceId, since);
    }

    /** The latest position of a device, also when it is older than any time window. */
    public Optional<DeviceLocation> latest(UUID accountId, UUID deviceId) {
        return deviceLocationRepository.findFirstByAccountIdAndDeviceIdOrderByRecordedAtDesc(accountId, deviceId);
    }
}
