package com.anpr.operations.internal.detections;

import com.anpr.operations.internal.alerts.model.Alert;
import com.anpr.operations.internal.alerts.repository.AlertRepository;
import com.anpr.operations.internal.detections.model.Detection;
import com.anpr.operations.internal.detections.model.DetectionFilter;
import com.anpr.operations.internal.detections.model.DetectionWithAlert;
import com.anpr.operations.internal.detections.repository.DetectionRepository;
import com.anpr.operations.internal.detections.repository.DetectionSpecification;
import com.anpr.operations.internal.detections.repository.PlateSuggestionRow;
import com.anpr.operations.shared.error.BadRequestException;
import com.anpr.operations.shared.error.ErrorCodes;
import com.anpr.operations.shared.security.CurrentAccount;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Limit;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

/** View 1: detection search and plate suggestions, always within the account of the caller. */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class DetectionSearchService {
    private final DetectionRepository detectionRepository;
    private final AlertRepository alertRepository;
    private final CurrentAccount currentAccount;

    public Page<DetectionWithAlert> search(DetectionFilter filter, Pageable pageable) {
        if (filter.from() != null && filter.to() != null && !filter.from().isBefore(filter.to())) {
            throw new BadRequestException(ErrorCodes.INVALID_TIME_RANGE, "'to' must be after 'from'");
        }
        UUID accountId = currentAccount.id();

        Specification<Detection> spec = DetectionSpecification.ofAccount(accountId);
        if (filter.plate() != null) {
            spec = spec.and(DetectionSpecification.plateEquals(filter.plate()));
        }
        if (filter.from() != null) {
            spec = spec.and(DetectionSpecification.detectedFrom(filter.from()));
        }
        if (filter.to() != null) {
            spec = spec.and(DetectionSpecification.detectedBefore(filter.to()));
        }

        Page<Detection> page = detectionRepository.findAll(spec, pageable);
        Map<String, UUID> alertIds = alertIdsByPlate(accountId, page.getContent());
        return page.map(detection -> new DetectionWithAlert(detection, alertIds.get(detection.getPlate())));
    }

    public List<PlateSuggestionRow> suggestPlates(String prefix, int limit) {
        return detectionRepository.findPlateSuggestions(currentAccount.id(), prefix, Limit.of(limit));
    }

    /** One query for the whole page instead of one per detection. */
    private Map<String, UUID> alertIdsByPlate(UUID accountId, List<Detection> detections) {
        if (detections.isEmpty()) {
            return Map.of();
        }
        Set<String> plates = detections.stream().map(Detection::getPlate).collect(Collectors.toSet());
        return alertRepository.findByAccountIdAndPlateIn(accountId, plates).stream()
                .collect(Collectors.toMap(Alert::getPlate, Alert::getAlertId));
    }
}