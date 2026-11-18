package com.anpr.operations.messaging.devices;

import com.anpr.operations.internal.devices.DevicePairingService;
import org.junit.jupiter.api.Test;
import software.amazon.awssdk.services.sqs.model.Message;
import software.amazon.awssdk.services.sqs.model.MessageAttributeValue;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.json.JsonMapper;

import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

class DeviceEventHandlerTest {
    private static final UUID DEVICE = UUID.fromString("7d3f2c1e-0000-4000-8000-000000000000");
    private static final UUID ACCOUNT = UUID.fromString("d1c2a0f8-0000-4000-8000-000000000000");

    private final DevicePairingService pairingService = mock(DevicePairingService.class);
    private final DeviceEventHandler handler = new DeviceEventHandler(JsonMapper.builder().build(), pairingService);

    @Test
    void pairedEventPairsTheDeviceAndIgnoresUnknownFields() {
        handler.handle(message("device.paired", """
                { "eventId": "0192f3a4-7c1e-7b2a-9d41-5f3e8a1c2b10", "occurredAt": "2026-11-01T10:00:00.000Z",
                  "version": 1, "deviceId": "%s", "accountId": "%s", "addedLater": true }
                """.formatted(DEVICE, ACCOUNT)));

        verify(pairingService).pair(DEVICE, ACCOUNT, 1);
    }

    @Test
    void unpairedEventUnpairsTheDevice() {
        handler.handle(message("device.unpaired", """
                { "version": 2, "deviceId": "%s" }
                """.formatted(DEVICE)));

        verify(pairingService).unpair(DEVICE, 2);
    }

    @Test
    void unknownEventTypeIsRejected() {
        assertThatThrownBy(() -> handler.handle(message("device.renamed", """
                { "version": 2, "deviceId": "%s" }
                """.formatted(DEVICE))))
                .isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(pairingService);
    }

    @Test
    void pairedEventWithoutAccountIsRejected() {
        assertThatThrownBy(() -> handler.handle(message("device.paired", """
                { "version": 1, "deviceId": "%s" }
                """.formatted(DEVICE))))
                .isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(pairingService);
    }

    @Test
    void malformedBodyIsRejected() {
        assertThatThrownBy(() -> handler.handle(message("device.paired", "{ not json")))
                .isInstanceOf(JacksonException.class);
        verifyNoInteractions(pairingService);
    }

    private static Message message(String eventType, String body) {
        return Message.builder()
                .messageId("message-1")
                .body(body)
                .messageAttributes(Map.of(
                        "eventType", stringAttribute(eventType),
                        "traceId", stringAttribute("trace-1")))
                .build();
    }

    private static MessageAttributeValue stringAttribute(String value) {
        return MessageAttributeValue.builder().dataType("String").stringValue(value).build();
    }
}
