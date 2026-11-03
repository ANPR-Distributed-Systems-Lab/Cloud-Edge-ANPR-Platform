package com.anpr.devicemanagement.shared.validation;

import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.FieldViolation;

import java.time.Duration;
import java.time.Instant;
import java.util.Optional;

/**
 * Accepted range of a timestamp sent by a device: not further in the future than its tolerated clock skew and not
 * older than {@code maxAge} (store-and-forward delivers old data, but only so old).
 */
public record TimestampWindow(Duration maxAge, Duration maxClockSkew) {

    public Optional<FieldViolation> check(Instant moment, Instant now, int index, String field) {
        if (moment.isAfter(now.plus(maxClockSkew))) {
            return Optional.of(new FieldViolation(index, field, ErrorCodes.TIMESTAMP_IN_FUTURE,
                    "must not be more than " + maxClockSkew.toMinutes() + " minutes in the future"));
        }
        if (moment.isBefore(now.minus(maxAge))) {
            return Optional.of(new FieldViolation(index, field, ErrorCodes.TIMESTAMP_TOO_OLD,
                    "must not be older than " + maxAge.toDays() + " days"));
        }
        return Optional.empty();
    }
}
