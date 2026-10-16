package com.anpr.operations.internal.alerts;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;
import java.util.UUID;

public interface AlertRepository extends JpaRepository<Alert, UUID> {

    Optional<Alert> findByAlertIdAndAccountId(UUID alertId, UUID accountId);

    boolean existsByAccountIdAndPlate(UUID accountId, String plate);

    Page<Alert> findByAccountId(UUID accountId, Pageable pageable);
}