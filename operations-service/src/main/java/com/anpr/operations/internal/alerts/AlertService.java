package com.anpr.operations.internal.alerts;

import com.anpr.operations.internal.alerts.model.Alert;
import com.anpr.operations.internal.alerts.model.AlertFilter;
import com.anpr.operations.internal.alerts.repository.AlertRepository;
import com.anpr.operations.internal.alerts.repository.AlertSpecification;
import com.anpr.operations.internal.alerts.repository.PlateAlert;
import com.anpr.operations.internal.devices.DevicePairingService;
import com.anpr.operations.shared.error.BadRequestException;
import com.anpr.operations.shared.error.ConflictException;
import com.anpr.operations.shared.error.ErrorCodes;
import com.anpr.operations.shared.error.ForbiddenException;
import com.anpr.operations.shared.error.NotFoundException;
import com.anpr.operations.shared.security.CurrentAccount;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.OffsetDateTime;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class AlertService {
    private final AlertRepository alertRepository;
    private final CurrentAccount currentAccount;
    private final Clock clock;
    private final DevicePairingService pairingService;

    @Transactional
    public Alert create(String plate, String alertText) {
        UUID accountId = currentAccount.id();
        if (alertRepository.existsByAccountIdAndPlate(accountId, plate)) {
            throw new ConflictException(ErrorCodes.ALERT_ALREADY_EXISTS, "Alert for this plate already exists");
        }
        Alert alert = Alert.create(accountId, plate, alertText, OffsetDateTime.now(clock));
        return alertRepository.save(alert);
    }

    public Alert get(UUID alertId) {
        return findOwned(alertId);
    }

    public Page<Alert> list(AlertFilter filters, Pageable pageable) {
        if (filters.from() != null && filters.to() != null && !filters.from().isBefore(filters.to())) {
            throw new BadRequestException(ErrorCodes.INVALID_TIME_RANGE, "'to' must be after 'from'");
        }

        Specification<Alert> spec = AlertSpecification.ofAccount(currentAccount.id());
        if (filters.plate() != null) {
            spec = spec.and(AlertSpecification.plateStartWith(filters.plate()));
        }
        if (filters.from() != null) {
            spec = spec.and(AlertSpecification.createAtFrom(filters.from()));
        }
        if (filters.to() != null) {
            spec = spec.and(AlertSpecification.createAtTo(filters.to()));
        }

        return alertRepository.findAll(spec, pageable);
    }

    @Transactional
    public Alert update(UUID alertId, String alertText, long version) {
        Alert alert = findOwned(alertId);
        if (!Objects.equals(alert.getVersion(), version)) {
            throw new ConflictException(ErrorCodes.CONCURRENT_MODIFICATION, "Alert was modified by someone else");
        }

        alert.update(alertText);
        return alertRepository.saveAndFlush(alert);
    }

    @Transactional
    public void delete(UUID alertId) {
        alertRepository.delete(findOwned(alertId));
    }

    public List<Alert> listForDevice() {
        UUID deviceId = currentAccount.id();
        UUID ownerId = pairingService.findOwner(deviceId).orElseThrow(() -> {
            log.warn("Device {} asked for alerts but has no owner", deviceId);
            return new ForbiddenException(ErrorCodes.DEVICE_NOT_PAIRED, "The device is not paired with an account");
        });
        return alertRepository.findAllByAccountIdOrderByCreatedAtAsc(ownerId);
    }

    /**
     * The alert of each plate, for the views that list detections (D14). One query for all plates of a page instead
     * of one per detection.
     */
    public Map<String, UUID> alertIdsByPlate(UUID accountId, Collection<String> plates) {
        if (plates.isEmpty()) {
            return Map.of();
        }
        return alertRepository.findAlertIdsByPlates(accountId, plates).stream()
                .collect(Collectors.toMap(PlateAlert::getPlate, PlateAlert::getAlertId));
    }

    private Alert findOwned(UUID alertId) {
        return alertRepository.findByAlertIdAndAccountId(alertId, currentAccount.id())
                .orElseThrow(() -> new NotFoundException(ErrorCodes.ALERT_NOT_FOUND, "Alert not found"));
    }
}
