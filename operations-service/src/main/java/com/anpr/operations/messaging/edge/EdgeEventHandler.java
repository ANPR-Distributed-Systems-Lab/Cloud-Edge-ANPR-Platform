package com.anpr.operations.messaging.edge;

import com.anpr.operations.internal.detections.DetectionService;
import com.anpr.operations.internal.detections.DetectionService.NewDetection;
import com.anpr.operations.internal.locations.DeviceLocationService;
import com.anpr.operations.internal.locations.DeviceLocationService.NewDeviceLocation;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.services.sqs.model.Message;
import tools.jackson.databind.json.JsonMapper;

import java.util.List;
import java.util.UUID;

import static com.anpr.operations.messaging.SqsMessages.attribute;

/**
 * Turns one message of the edge events queue (a batch of detections or of GPS points of one device) into stored rows.
 * Any exception leaves the message on the queue: it is retried and goes to the DLQ after 5 receives.
 */
@Component
@RequiredArgsConstructor
public class EdgeEventHandler {
    static final String DETECTION = "detection";
    static final String DEVICE_LOCATION = "device-location";

    private final JsonMapper jsonMapper;
    private final DetectionService detectionService;
    private final DeviceLocationService deviceLocationService;

    public void handle(Message message) {
        // The device comes from its token (set by the Lambda), never from the body.
        String deviceId = attribute(message, "deviceId");
        if (deviceId == null) {
            throw new IllegalArgumentException("Edge event without deviceId");
        }
        String eventType = attribute(message, "eventType");
        switch (eventType == null ? "" : eventType) {
            case DETECTION -> storeDetections(UUID.fromString(deviceId), message.body());
            case DEVICE_LOCATION -> storeLocations(UUID.fromString(deviceId), message.body());
            default -> throw new IllegalArgumentException("Unknown edge event type: " + eventType);
        }
    }

    private void storeDetections(UUID deviceId, String body) {
        DetectionBatchMessage batch = jsonMapper.readValue(body, DetectionBatchMessage.class);
        List<NewDetection> detections = batch.detections().stream()
                .map(d -> new NewDetection(d.detectionId(), d.plate(), d.detectedAt(),
                        d.location().lat(), d.location().lon(),
                        d.ocrConfidence(), d.detectorConfidence(), d.imageKey()))
                .toList();
        detectionService.store(deviceId, detections);
    }

    private void storeLocations(UUID deviceId, String body) {
        LocationBatchMessage batch = jsonMapper.readValue(body, LocationBatchMessage.class);
        List<NewDeviceLocation> locations = batch.locations().stream()
                .map(l -> new NewDeviceLocation(l.locationId(), l.recordedAt(), l.lat(), l.lon()))
                .toList();
        deviceLocationService.store(deviceId, locations);
    }
}
