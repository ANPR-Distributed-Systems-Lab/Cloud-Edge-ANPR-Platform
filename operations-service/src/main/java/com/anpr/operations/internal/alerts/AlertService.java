package com.anpr.operations.internal.alerts;

import com.anpr.operations.internal.alerts.model.Alert;
import com.anpr.operations.internal.alerts.model.AlertFilter;
import com.anpr.operations.internal.alerts.repository.AlertRepository;
import com.anpr.operations.internal.alerts.repository.AlertSpecification;
import com.anpr.operations.internal.alerts.repository.AlertVersion;
import com.anpr.operations.internal.alerts.repository.PlateAlert;
import com.anpr.operations.internal.devices.DevicePairingService;
import com.anpr.operations.shared.error.ConflictException;
import com.anpr.operations.shared.error.ErrorCodes;
import com.anpr.operations.shared.error.ForbiddenException;
import com.anpr.operations.shared.error.NotFoundException;
import com.anpr.operations.shared.security.CurrentAccount;
import jakarta.persistence.EntityManager;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.hibernate.exception.ConstraintViolationException;
import org.springframework.dao.DataIntegrityViolationException;
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
    private static final String PLATE_UNIQUE_CONSTRAINT = "uq_alerts_account_plate";

    private final AlertRepository alertRepository;
    private final CurrentAccount currentAccount;
    private final Clock clock;
    private final DevicePairingService pairingService;
    private final EntityManager entityManager;

    @Transactional
    public Alert create(String plate, String alertText) {
        UUID accountId = currentAccount.id();
        if (alertRepository.existsByAccountIdAndPlate(accountId, plate)) {
            throw new ConflictException(ErrorCodes.ALERT_ALREADY_EXISTS, "Alert for this plate already exists");
        }
        Alert alert = Alert.create(accountId, plate, alertText, OffsetDateTime.now(clock));
        try {
            // Flushed here so that a concurrent create of the same plate fails inside this method, not at commit.
            Alert saved = alertRepository.saveAndFlush(alert);
            // Read back so the database computes lastDetectedAt (@Formula): the plate may have been detected before.
            entityManager.refresh(saved);
            return saved;
        } catch (DataIntegrityViolationException e) {
            if (violates(e, PLATE_UNIQUE_CONSTRAINT)) {
                throw new ConflictException(ErrorCodes.ALERT_ALREADY_EXISTS, "Alert for this plate already exists", e);
            }
            throw e;
        }
    }

    public Alert get(UUID alertId) {
        return findOwned(alertId);
    }

    public Page<Alert> list(AlertFilter filters, Pageable pageable) {
        Specification<Alert> spec = AlertSpecification.ofAccount(currentAccount.id());
        if (filters.plate() != null) {
            spec = spec.and(AlertSpecification.plateStartsWith(filters.plate()));
        }
        if (filters.period().from() != null) {
            spec = spec.and(AlertSpecification.createdFrom(filters.period().from()));
        }
        if (filters.period().to() != null) {
            spec = spec.and(AlertSpecification.createdBefore(filters.period().to()));
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

    /** Every alert of the owner of the calling device. */
    public List<Alert> listForDevice() {
        return alertRepository.findAllByAccountIdOrderByCreatedAtAsc(ownerOfDevice());
    }

    /** Id and version of every alert of the owner of the calling device: a cheap check whether the list changed. */
    public List<AlertVersion> versionsForDevice() {
        return alertRepository.findVersionsByAccountId(ownerOfDevice());
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

    private static boolean violates(DataIntegrityViolationException e, String constraint) {
        for (Throwable cause = e; cause != null; cause = cause.getCause()) {
            if (cause instanceof ConstraintViolationException violation) {
                return constraint.equalsIgnoreCase(violation.getConstraintName());
            }
        }
        return false;
    }

    private UUID ownerOfDevice() {
        UUID deviceId = currentAccount.id();
        return pairingService.findOwner(deviceId).orElseThrow(() -> {
            log.warn("Device {} asked for alerts but has no owner", deviceId);
            return new ForbiddenException(ErrorCodes.DEVICE_NOT_PAIRED, "The device is not paired with an account");
        });
    }

    private Alert findOwned(UUID alertId) {
        return alertRepository.findByAlertIdAndAccountId(alertId, currentAccount.id())
                .orElseThrow(() -> new NotFoundException(ErrorCodes.ALERT_NOT_FOUND, "Alert not found"));
    }
}
