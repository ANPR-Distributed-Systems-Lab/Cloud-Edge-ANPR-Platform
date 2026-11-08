package com.anpr.operations.internal.alerts.repository;

import com.anpr.operations.internal.alerts.model.Alert;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;

import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface AlertRepository extends JpaRepository<Alert, UUID>, JpaSpecificationExecutor<Alert> {

    Optional<Alert> findByAlertIdAndAccountId(UUID alertId, UUID accountId);

    boolean existsByAccountIdAndPlate(UUID accountId, String plate);

    List<Alert> findAllByAccountIdOrderByCreatedAtAsc(UUID accountId);

    List<Alert> findByAccountIdAndPlateIn(UUID accountId, Collection<String> plates);
}
