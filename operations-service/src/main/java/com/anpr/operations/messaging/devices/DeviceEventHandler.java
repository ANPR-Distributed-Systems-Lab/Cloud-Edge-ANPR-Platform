package com.anpr.operations.messaging.devices;

import com.anpr.operations.internal.devices.DevicePairingService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.services.sqs.model.Message;
import tools.jackson.databind.json.JsonMapper;

import java.util.UUID;

import static com.anpr.operations.messaging.SqsMessages.attribute;

/**
 * Turns one message of the device-events queue into a pairing change. Any exception leaves the message on the
 * queue: it returns after the visibility timeout and goes to the DLQ after 5 receives.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class DeviceEventHandler {
    static final String PAIRED = "device.paired";
    static final String UNPAIRED = "device.unpaired";

    private final JsonMapper jsonMapper;
    private final DevicePairingService pairingService;

    public void handle(Message message) {
        String eventType = attribute(message, "eventType");
        DeviceEventMessage event = jsonMapper.readValue(message.body(), DeviceEventMessage.class);
        UUID deviceId = required(event.deviceId(), "deviceId");
        long version = required(event.version(), "version");

        switch (eventType == null ? "" : eventType) {
            case PAIRED -> pairingService.pair(deviceId, required(event.accountId(), "accountId"), version);
            case UNPAIRED -> pairingService.unpair(deviceId, version);
            default -> throw new IllegalArgumentException("Unknown device event type: " + eventType);
        }
        log.info("Handled {} of device {} with version {}", eventType, deviceId, version);
    }

    private static <T> T required(T value, String field) {
        if (value == null) {
            throw new IllegalArgumentException("Device event without " + field);
        }
        return value;
    }
}
