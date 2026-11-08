package com.anpr.operations.internal.detections.repository;

import com.anpr.operations.internal.detections.model.Detection;
import lombok.AccessLevel;
import lombok.NoArgsConstructor;
import org.springframework.data.jpa.domain.Specification;

import java.time.OffsetDateTime;
import java.util.UUID;

@NoArgsConstructor(access = AccessLevel.PRIVATE)
public final class DetectionSpecification {
    public static Specification<Detection> ofAccount(UUID accountId) {
        return (root, query, cb) ->
                cb.equal(root.get("accountId"), accountId);
    }

    public static Specification<Detection> plateEquals(String plate) {
        return (root, query, cb) ->
                cb.equal(root.get("plate"), plate);
    }

    public static Specification<Detection> detectedFrom(OffsetDateTime from) {
        return (root, query, cb) -> cb.greaterThanOrEqualTo(root.get("detectedAt"), from);
    }

    public static Specification<Detection> detectedBefore(OffsetDateTime to) {
        return (root, query, cb) -> cb.lessThan(root.get("detectedAt"), to);
    }

}
