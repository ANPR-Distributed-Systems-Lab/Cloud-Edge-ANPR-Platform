package com.anpr.operations.internal.locations;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;

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
}
