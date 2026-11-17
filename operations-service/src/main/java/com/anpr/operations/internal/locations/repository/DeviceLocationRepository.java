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

    /** The latest position, also when it is older than any time window. Native like findTrack, same columns. */
    @Query(value = """
            SELECT recorded_at AS "recordedAt", ST_Y(position::geometry) AS "lat", ST_X(position::geometry) AS "lon"
            FROM device_locations
            WHERE account_id = :accountId AND device_id = :deviceId
            ORDER BY recorded_at DESC
            LIMIT 1
            """, nativeQuery = true)
    Optional<LocationPoint> findLatest(UUID accountId, UUID deviceId);

    /**
     * Route since the given time, oldest point first, with at most one point per 10 seconds (the last fix of each):
     * a 60-minute live feed window stays within 360 points however often the device sends GPS fixes.
     */
    @Query(value = """
            SELECT DISTINCT ON (date_bin('10 seconds', recorded_at, TIMESTAMPTZ 'epoch'))
                   recorded_at AS "recordedAt", ST_Y(position::geometry) AS "lat", ST_X(position::geometry) AS "lon"
            FROM device_locations
            WHERE account_id = :accountId AND device_id = :deviceId AND recorded_at >= :since
            ORDER BY date_bin('10 seconds', recorded_at, TIMESTAMPTZ 'epoch'), recorded_at DESC
            """, nativeQuery = true)
    List<LocationPoint> findTrack(UUID accountId, UUID deviceId, OffsetDateTime since);
}