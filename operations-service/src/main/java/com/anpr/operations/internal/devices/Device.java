package com.anpr.operations.internal.devices;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.util.UUID;

/**
 * Local copy of the owner of a device, built from the events of device-management (docs/events/device-events.md).
 * The row is never deleted: unpairing clears the owner and keeps the version.
 */
@Entity
@Table(name = "devices")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Device {
    @Id
    private UUID deviceId;

    /** The owning account; null after the device was unpaired. */
    private UUID accountId;

    /** Ownership version from the events. Not a JPA @Version: set by device-management, never raised here. */
    private long version;

    public static Device paired(UUID deviceId, UUID accountId, long version) {
        Device device = new Device();
        device.deviceId = deviceId;
        device.accountId = accountId;
        device.version = version;
        return device;
    }

    /** An unpairing that arrived before its pairing: the row only remembers the version. */
    public static Device unpaired(UUID deviceId, long version) {
        return paired(deviceId, null, version);
    }

    /** Equal or older events are duplicates or arrived out of order, and are ignored. */
    public boolean isOlderThan(long eventVersion) {
        return eventVersion > version;
    }

    public void pair(UUID accountId, long version) {
        this.accountId = accountId;
        this.version = version;
    }

    public void unpair(long version) {
        this.accountId = null;
        this.version = version;
    }
}
