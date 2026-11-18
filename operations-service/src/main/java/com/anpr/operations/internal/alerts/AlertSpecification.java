package com.anpr.operations.internal.alerts;

import lombok.AccessLevel;
import lombok.NoArgsConstructor;
import org.springframework.data.jpa.domain.Specification;

import java.time.OffsetDateTime;
import java.util.UUID;

@NoArgsConstructor(access = AccessLevel.PRIVATE)
final class AlertSpecification {
    static Specification<Alert> ofAccount(UUID accountId) {
        return (root, query, cb) -> cb.equal(root.get("accountId"), accountId);
    }

    // The contract validates the prefix as [A-Z0-9], so it is already uppercase and needs no LIKE escaping.
    static Specification<Alert> plateStartWith(String prefix) {
        return (root, query, cb) -> cb.like(root.get("plate"), prefix + "%");
    }

    static Specification<Alert> createAtFrom(OffsetDateTime from) {
        return (root, query, cb) -> cb.greaterThanOrEqualTo(root.get("createdAt"), from);
    }

    static Specification<Alert> createAtTo(OffsetDateTime to) {
        return (root, query, cb) -> cb.lessThan(root.get("createdAt"), to);
    }
}
