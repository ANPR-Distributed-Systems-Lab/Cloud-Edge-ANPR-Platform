package com.anpr.operations.messaging.edge;

import com.anpr.operations.internal.detections.DetectionService.NewDetection;
import com.anpr.operations.internal.detections.DetectionService;
import com.anpr.operations.internal.locations.DeviceLocationService.NewDeviceLocation;
import com.anpr.operations.internal.locations.DeviceLocationService;
import org.junit.jupiter.api.Test;
import software.amazon.awssdk.services.sqs.model.Message;
import software.amazon.awssdk.services.sqs.model.MessageAttributeValue;
import tools.jackson.databind.json.JsonMapper;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

class EdgeEventHandlerTest {
    private static final UUID DEVICE = UUID.fromString("7d3f2c1e-0000-4000-8000-000000000000");

    private final DetectionService detectionService = mock(DetectionService.class);
    private final DeviceLocationService deviceLocationService = mock(DeviceLocationService.class);
    private final EdgeEventHandler handler =
            new EdgeEventHandler(JsonMapper.builder().build(), detectionService, deviceLocationService);

    @Test
    void detectionBatchIsStoredForTheDeviceOfTheToken() throws IOException {
        handler.handle(message("detection", DEVICE.toString(), resource("detection-batch.json")));

        verify(detectionService).store(DEVICE, List.of(new NewDetection(
                UUID.fromString("0192f3a4-7c1f-7e11-8a02-6b7d4c9e1a01"), "WA12345",
                OffsetDateTime.parse("2026-10-30T09:14:22.381Z"), 52.229676, 21.012229, 0.94, 0.88,
                "images/7d3f2c1e-0000-4000-8000-000000000000/2026/10/30/0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c.jpg")));
    }

    @Test
    void locationBatchIsStoredForTheDeviceOfTheToken() throws IOException {
        handler.handle(message("device-location", DEVICE.toString(), resource("location-batch.json")));

        verify(deviceLocationService).store(DEVICE, List.of(new NewDeviceLocation(
                UUID.fromString("0192f3a4-9a11-7d20-9c01-3b5d7f9a1c02"),
                OffsetDateTime.parse("2026-10-30T09:14:21.000Z"), 52.229676, 21.012229)));
    }

    @Test
    void unknownEventTypeIsRejected() throws IOException {
        assertThatThrownBy(() -> handler.handle(message("device-status", DEVICE.toString(), resource("location-batch.json"))))
                .isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(detectionService, deviceLocationService);
    }

    @Test
    void eventWithoutDeviceIsRejected() throws IOException {
        assertThatThrownBy(() -> handler.handle(message("detection", null, resource("detection-batch.json"))))
                .isInstanceOf(IllegalArgumentException.class);
        verifyNoInteractions(detectionService, deviceLocationService);
    }

    private static Message message(String eventType, String deviceId, String body) {
        Map<String, MessageAttributeValue> attributes = new HashMap<>();
        attributes.put("eventType", stringAttribute(eventType));
        attributes.put("traceId", stringAttribute("trace-1"));
        if (deviceId != null) {
            attributes.put("deviceId", stringAttribute(deviceId));
        }
        return Message.builder().messageId("message-1").body(body).messageAttributes(attributes).build();
    }

    private static MessageAttributeValue stringAttribute(String value) {
        return MessageAttributeValue.builder().dataType("String").stringValue(value).build();
    }

    private static String resource(String name) throws IOException {
        try (InputStream in = EdgeEventHandlerTest.class.getResourceAsStream("/messaging/edge/" + name)) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8);
        }
    }
}
