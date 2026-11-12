package com.anpr.operations.internal.alerts.repository;

import com.anpr.operations.internal.alerts.model.Alert;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.data.jpa.repository.Query;

import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface AlertRepository extends JpaRepository<Alert, UUID>, JpaSpecificationExecutor<Alert> {

    Optional<Alert> findByAlertIdAndAccountId(UUID alertId, UUID accountId);

    boolean existsByAccountIdAndPlate(UUID accountId, String plate);

    List<Alert> findAllByAccountIdOrderByCreatedAtAsc(UUID accountId);

    /** Only the two columns: loading whole alerts would also compute lastDetectedAt (@Formula) for nothing. */
    @Query("""
            SELECT a.plate AS plate, a.alertId AS alertId FROM Alert a
            WHERE a.accountId = :accountId AND a.plate IN :plates
            """)
    List<PlateAlert> findAlertIdsByPlates(UUID accountId, Collection<String> plates);
}
