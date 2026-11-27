package com.anpr.operations.internal.detections.model;

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

/**
 * One ANPR detection. Written once from an edge event and never changed. accountId is the owner of the device at the
 * time of writing, so the history stays with that owner when the device changes hands.
 */
@Entity
@Table(name = "detections")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Detection {
    @Id
    private UUID detectionId;
    private UUID accountId;
    private UUID deviceId;
    private String plate;
    private OffsetDateTime detectedAt;
    @Column(columnDefinition = "geography(Point,4326)")
    private Point position;
    private double ocrConfidence;
    private double detectorConfidence;
    private String imageKey;
    /** Set by the database when the row is stored (V4); the order of the live feed. */
    @Column(insertable = false, updatable = false)
    private OffsetDateTime ingestedAt;

    public static Detection create(UUID detectionId, UUID accountId, UUID deviceId, String plate,
                                   OffsetDateTime detectedAt, Point position, double ocrConfidence,
                                   double detectorConfidence, String imageKey) {
        Detection detection = new Detection();
        detection.detectionId = detectionId;
        detection.accountId = accountId;
        detection.deviceId = deviceId;
        detection.plate = plate;
        detection.detectedAt = detectedAt;
        detection.position = position;
        detection.ocrConfidence = ocrConfidence;
        detection.detectorConfidence = detectorConfidence;
        detection.imageKey = imageKey;
        return detection;
    }
}
