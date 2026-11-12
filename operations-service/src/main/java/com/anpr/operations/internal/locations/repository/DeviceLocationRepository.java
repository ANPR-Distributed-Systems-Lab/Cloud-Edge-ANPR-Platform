package com.anpr.operations.internal.locations.repository;

import com.anpr.operations.internal.locations.model.DeviceLocation;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;

import java.util.UUID;

public interface DeviceLocationRepository extends JpaRepository<DeviceLocation, UUID> {

    /** Returns 0 when the point is already stored, 1 when it was inserted. */
    @Modifying
    @Query(value = """
            INSERT INTO device_locations (location_id, account_id, device_id, recorded_at, position)
            VALUES (:#{#location.locationId}, :#{#location.accountId}, :#{#location.deviceId},
                    :#{#location.recordedAt}, :#{#location.position})
            ON CONFLICT (location_id) DO NOTHING
            """, nativeQuery = true)
    int insertIfAbsent(DeviceLocation location);

    Optional<DeviceLocation> findFirstByAccountIdAndDeviceIdOrderByRecordedAtDesc(UUID accountId, UUID deviceId);

    @Query("""
            SELECT l FROM DeviceLocation l
            WHERE l.accountId = :accountId AND l.deviceId = :deviceId AND l.recordedAt >= :since
            ORDER BY l.recordedAt
            """)
    List<DeviceLocation> findTrack(UUID accountId, UUID deviceId, OffsetDateTime since);
}