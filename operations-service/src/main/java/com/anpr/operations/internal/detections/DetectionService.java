package com.anpr.operations.internal.detections;

import com.anpr.operations.internal.detections.model.Detection;
import com.anpr.operations.internal.detections.repository.DetectionRepository;
import com.anpr.operations.internal.devices.DeviceOwners;
import com.anpr.operations.shared.geo.Wgs84;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class DetectionService {
    private final DetectionRepository detectionRepository;
    private final DeviceOwners deviceOwners;

    /** A detection as the device reported it, before the owner is known. */
    public record NewDetection(UUID detectionId, String plate, OffsetDateTime detectedAt, double lat, double lon,
                               double ocrConfidence, double detectorConfidence, String imageKey) {
    }

    /** Stores a batch of one device in one transaction: either all new detections are stored, or none. */
    @Transactional
    public void store(UUID deviceId, List<NewDetection> detections) {
        UUID ownerId = deviceOwners.require(deviceId);
        int inserted = 0;
        for (NewDetection d : detections) {
            inserted += detectionRepository.insertIfAbsent(Detection.create(
                    d.detectionId(), ownerId, deviceId, d.plate(), d.detectedAt(), Wgs84.point(d.lat(), d.lon()),
                    d.ocrConfidence(), d.detectorConfidence(), d.imageKey()));
        }
        log.debug("Stored {} new of {} detections of device {}", inserted, detections.size(), deviceId);
    }
}
