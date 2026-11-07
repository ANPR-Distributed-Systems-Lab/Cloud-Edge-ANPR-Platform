package com.anpr.operations.internal.detections;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;

import java.util.UUID;

public interface DetectionRepository extends JpaRepository<Detection, UUID> {

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
}
