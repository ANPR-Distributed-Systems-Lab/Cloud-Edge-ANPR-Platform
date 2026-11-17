package com.anpr.operations.internal.detections;

import com.anpr.operations.internal.alerts.AlertService;
import com.anpr.operations.internal.detections.model.Detection;
import com.anpr.operations.internal.detections.model.DetectionFilter;
import com.anpr.operations.internal.detections.model.DetectionWithAlert;
import com.anpr.operations.internal.detections.repository.DetectionRepository;
import com.anpr.operations.internal.detections.repository.DetectionSpecification;
import com.anpr.operations.internal.detections.repository.PlateSuggestionRow;
import com.anpr.operations.internal.devices.DevicePairingService;
import com.anpr.operations.shared.error.ErrorCodes;
import com.anpr.operations.shared.error.NotFoundException;
import com.anpr.operations.shared.geo.Wgs84;
import com.anpr.operations.shared.security.CurrentAccount;
import com.anpr.operations.shared.time.TimeRange;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Limit;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

/** Detections: stored from the edge events queue, read by Views 1, 2 and 3 and D18 (one detection). */
@Slf4j
@Service
@RequiredArgsConstructor
public class DetectionService {
    private final DetectionRepository detectionRepository;
    private final DevicePairingService pairingService;
    private final AlertService alertService;
    private final CurrentAccount currentAccount;

    /** A detection as the device reported it, before the owner is known. */
    public record NewDetection(UUID detectionId, String plate, OffsetDateTime detectedAt, double lat, double lon,
                               double ocrConfidence, double detectorConfidence, String imageKey) {
    }

    /** Stores a batch of one device in one transaction: either all new detections are stored, or none. */
    @Transactional
    public void store(UUID deviceId, List<NewDetection> detections) {
        UUID ownerId = pairingService.requireOwner(deviceId);
        int inserted = 0;
        for (NewDetection d : detections) {
            inserted += detectionRepository.insertIfAbsent(Detection.create(
                    d.detectionId(), ownerId, deviceId, d.plate(), d.detectedAt(), Wgs84.point(d.lat(), d.lon()),
                    d.ocrConfidence(), d.detectorConfidence(), d.imageKey()));
        }
        log.debug("Stored {} new of {} detections of device {}", inserted, detections.size(), deviceId);
    }

    /**
     * One detection of the caller's account (D18). A detection of another account is reported as not found, so the
     * response does not reveal which ids exist.
     */
    @Transactional(readOnly = true)
    public DetectionWithAlert get(UUID detectionId) {
        UUID accountId = currentAccount.id();
        Detection detection = detectionRepository.findByDetectionIdAndAccountId(detectionId, accountId)
                .orElseThrow(() -> new NotFoundException(ErrorCodes.DETECTION_NOT_FOUND, "Detection not found"));
        return withAlerts(accountId, List.of(detection)).getFirst();
    }

    /** View 1: detections of the caller's account by optional exact plate and time range. */
    @Transactional(readOnly = true)
    public Page<DetectionWithAlert> search(DetectionFilter filter, Pageable pageable) {
        UUID accountId = currentAccount.id();

        Specification<Detection> spec = DetectionSpecification.ofAccount(accountId);
        if (filter.plate() != null) {
            spec = spec.and(DetectionSpecification.plateEquals(filter.plate()));
        }
        if (filter.period().from() != null) {
            spec = spec.and(DetectionSpecification.detectedFrom(filter.period().from()));
        }
        if (filter.period().to() != null) {
            spec = spec.and(DetectionSpecification.detectedBefore(filter.period().to()));
        }

        Page<Detection> page = detectionRepository.findAll(spec, pageable);
        return new PageImpl<>(withAlerts(accountId, page.getContent()), pageable, page.getTotalElements());
    }

    /** View 1: distinct plates of the caller's account by prefix, most recently detected first. */
    @Transactional(readOnly = true)
    public List<PlateSuggestionRow> suggestPlates(String prefix, int limit) {
        // The contract allows only A-Z and 0-9 in the prefix, so it cannot carry LIKE wildcards of its own.
        return detectionRepository.findPlateSuggestions(currentAccount.id(), prefix + "%", Limit.of(limit));
    }

    /** View 3, first poll: the most recently stored detections, newest first. */
    @Transactional(readOnly = true)
    public List<DetectionWithAlert> latestStored(UUID accountId, OffsetDateTime storedUntil, int limit) {
        return withAlerts(accountId, detectionRepository.findLatestStored(accountId, storedUntil, Limit.of(limit)));
    }

    /** View 3, next polls: detections stored after the given one, in the order they were stored. */
    @Transactional(readOnly = true)
    public List<DetectionWithAlert> storedAfter(UUID accountId, OffsetDateTime afterStoredAt, UUID afterId,
                                                OffsetDateTime storedUntil, int limit) {
        return withAlerts(accountId, detectionRepository.findStoredAfter(accountId, afterStoredAt, afterId,
                storedUntil, Limit.of(limit)));
    }

    /** View 2: detections within the radius, newest first, with their alerts. */
    @Transactional(readOnly = true)
    public List<DetectionWithAlert> withinRadius(UUID accountId, double lat, double lon, int radiusMeters,
                                                 TimeRange period, int limit) {
        return withAlerts(accountId, detectionRepository.findWithinRadius(accountId, lat, lon, radiusMeters,
                period.from(), period.to(), limit));
    }

    private List<DetectionWithAlert> withAlerts(UUID accountId, List<Detection> detections) {
        Map<String, UUID> alertIds = alertIdsOf(accountId, detections);
        return detections.stream()
                .map(detection -> new DetectionWithAlert(detection, alertIds.get(detection.getPlate())))
                .toList();
    }

    /** One query for all plates of a page instead of one per detection. */
    private Map<String, UUID> alertIdsOf(UUID accountId, List<Detection> detections) {
        return alertService.alertIdsByPlate(accountId,
                detections.stream().map(Detection::getPlate).collect(Collectors.toSet()));
    }
}
