package com.anpr.devicemanagement.local;

import com.anpr.devicemanagement.internal.provisioning.DeviceEvents;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

import java.util.UUID;

/** Stand-in for the device-events topic on a developer machine, which never publishes to SNS on AWS (CLAUDE.md). */
@Slf4j
@Component
@Profile("local")
public class LoggingDeviceEvents implements DeviceEvents {

    @Override
    public void paired(UUID deviceId, UUID accountId, long version) {
        log.atInfo().addKeyValue("eventType", "device.paired").addKeyValue("deviceId", deviceId)
                .addKeyValue("accountId", accountId).addKeyValue("version", version).log("Device event not published (local)");
    }

    @Override
    public void unpaired(UUID deviceId, long version) {
        log.atInfo().addKeyValue("eventType", "device.unpaired").addKeyValue("deviceId", deviceId)
                .addKeyValue("version", version).log("Device event not published (local)");
    }
}
