package com.anpr.operations.internal.detections.repository;

import com.anpr.operations.internal.detections.model.Detection;
import org.springframework.data.domain.Limit;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

public interface DetectionRepository extends JpaRepository<Detection, UUID>, JpaSpecificationExecutor<Detection> {

    /** Returns 0 when the detection is already stored (a redelivered message), 1 when it was inserted. */
    @Modifying
    @Query(value = """
            INSERT INTO detections (detection_id, account_id, device_id, plate, detected_at, position,
                                    ocr_confidence, detector_confidence, image_key)
            VALUES (:#{#detection.detectionId}, :#{#detection.accountId}, :#{#detection.deviceId},
                    :#{#detection.plate}, :#{#detection.detectedAt}, :#{#detection.position},
                    :#{#detection.ocrConfidence}, :#{#detection.detectorConfidence}, :#{#detection.imageKey})
            ON CONFLICT (detection_id) DO NOTHING
            """, nativeQuery = true)
    int insertIfAbsent(Detection detection);

    /** Distinct plates of the account starting with the prefix, most recently detected first. */
    @Query("""
            SELECT d.plate AS plate, MAX(d.detectedAt) AS lastDetectedAt
            FROM Detection d
            WHERE d.accountId = :accountId AND d.plate LIKE CONCAT(:prefix, '%')
            GROUP BY d.plate
            ORDER BY MAX(d.detectedAt) DESC
            """)
    List<PlateSuggestionRow> findPlateSuggestions(UUID accountId, String prefix, Limit limit);

    /** Live feed, first poll: the most recently stored detections, newest first. */
    @Query("""
            SELECT d FROM Detection d
            WHERE d.accountId = :accountId AND d.ingestedAt <= :storedUntil
            ORDER BY d.ingestedAt DESC, d.detectionId DESC
            """)
    List<Detection> findLatestStored(UUID accountId, OffsetDateTime storedUntil, Limit limit);

    /** Live feed, next polls: detections stored after the cursor, in the order they were stored. */
    @Query("""
            SELECT d FROM Detection d
            WHERE d.accountId = :accountId AND d.ingestedAt <= :storedUntil
              AND (d.ingestedAt > :afterStoredAt OR (d.ingestedAt = :afterStoredAt AND d.detectionId > :afterId))
            ORDER BY d.ingestedAt, d.detectionId
            """)
    List<Detection> findStoredAfter(UUID accountId, OffsetDateTime afterStoredAt, UUID afterId,
                                    OffsetDateTime storedUntil, Limit limit);
}
