package com.anpr.operations.internal.locations.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.locationtech.jts.geom.Point;

import java.time.OffsetDateTime;
import java.util.UUID;

/** One point of the GPS track of a device. Written once; accountId is the owner at the time of writing. */
@Entity
@Table(name = "device_locations")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class DeviceLocation {
    @Id
    private UUID locationId;
    private UUID accountId;
    private UUID deviceId;
    private OffsetDateTime recordedAt;
    @Column(columnDefinition = "geography(Point,4326)")
    private Point position;

    public static DeviceLocation create(UUID locationId, UUID accountId, UUID deviceId,
                                        OffsetDateTime recordedAt, Point position) {
        DeviceLocation location = new DeviceLocation();
        location.locationId = locationId;
        location.accountId = accountId;
        location.deviceId = deviceId;
        location.recordedAt = recordedAt;
        location.position = position;
        return location;
    }
}
