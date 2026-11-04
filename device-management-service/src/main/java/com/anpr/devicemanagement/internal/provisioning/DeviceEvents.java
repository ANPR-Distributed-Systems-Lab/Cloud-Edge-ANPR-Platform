package com.anpr.devicemanagement.internal.provisioning;

import java.util.UUID;

/**
 * Announces changes of ownership to the other services (docs/events/device-events.md). A method returns once the
 * event is published and throws when it could not be.
 */
public interface DeviceEvents {

    void paired(UUID deviceId, UUID accountId, long version);

    void unpaired(UUID deviceId, long version);
}
