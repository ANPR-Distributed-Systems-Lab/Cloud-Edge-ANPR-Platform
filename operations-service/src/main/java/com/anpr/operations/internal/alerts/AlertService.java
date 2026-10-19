package com.anpr.operations.internal.alerts;

import com.anpr.operations.shared.error.ConflictException;
import com.anpr.operations.shared.error.ErrorCodes;
import com.anpr.operations.shared.error.NotFoundException;
import com.anpr.operations.shared.security.CurrentAccount;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.OffsetDateTime;
import java.util.Objects;
import java.util.UUID;

@Service
@RequiredArgsConstructor
public class AlertService {
    private final AlertRepository alertRepository;
    private final CurrentAccount currentAccount;
    private final Clock clock;

    @Transactional
    public Alert create(String plate, String alertText) {
        UUID accountId = currentAccount.id();
        if (alertRepository.existsByAccountIdAndPlate(accountId, plate)) {
            throw new ConflictException(ErrorCodes.ALERT_ALREADY_EXISTS, "Alert for this plate already exists");
        }
        Alert alert = Alert.create(accountId, plate, alertText, OffsetDateTime.now(clock));
        return alertRepository.save(alert);
    }

    @Transactional(readOnly = true)
    public Alert get(UUID alertId) {
        return findOwned(alertId);
    }

    @Transactional(readOnly = true)
    public Page<Alert> list(Pageable pageable) {
        return alertRepository.findByAccountId(currentAccount.id(), pageable);
    }

    @Transactional
    public Alert update(UUID alertId, String plate, String alertText, long version) {
        Alert alert = findOwned(alertId);
        if (!Objects.equals(alert.getVersion(), version)) {
            throw new ConflictException(ErrorCodes.CONCURRENT_MODIFICATION, "Alert was modified by someone else");
        }
        if (!alert.getPlate().equals(plate)
                && alertRepository.existsByAccountIdAndPlate(alert.getAccountId(), plate)) {
            throw new ConflictException(ErrorCodes.ALERT_ALREADY_EXISTS, "Alert for this plate already exists");
        }

        alert.update(plate, alertText);
        return alertRepository.saveAndFlush(alert);
    }

    @Transactional
    public void delete(UUID alertId) {
        alertRepository.delete(findOwned(alertId));
    }

    private Alert findOwned(UUID alertId) {
        return alertRepository.findByAlertIdAndAccountId(alertId, currentAccount.id())
                .orElseThrow(() -> new NotFoundException(ErrorCodes.ALERT_NOT_FOUND, "Alert not found"));
    }
}
