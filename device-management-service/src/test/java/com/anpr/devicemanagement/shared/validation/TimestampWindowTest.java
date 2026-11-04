package com.anpr.devicemanagement.shared.validation;

import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.FieldViolation;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.time.Instant;

import static org.assertj.core.api.Assertions.assertThat;

class TimestampWindowTest {

    private static final Instant NOW = Instant.parse("2026-11-02T10:00:00Z");
    private final TimestampWindow window = new TimestampWindow(Duration.ofDays(7), Duration.ofMinutes(5));

    @Test
    void acceptsTheWholeWindowIncludingItsBounds() {
        assertThat(window.check(NOW, NOW, 0, "f")).isEmpty();
        assertThat(window.check(NOW.plus(Duration.ofMinutes(5)), NOW, 0, "f")).isEmpty();
        assertThat(window.check(NOW.minus(Duration.ofDays(7)), NOW, 0, "f")).isEmpty();
    }

    @Test
    void refusesTooFarInTheFuture() {
        assertThat(window.check(NOW.plus(Duration.ofMinutes(5)).plusMillis(1), NOW, 2, "metrics[2].recordedAt"))
                .map(FieldViolation::code).contains(ErrorCodes.TIMESTAMP_IN_FUTURE);
    }

    @Test
    void refusesTooOldWithTheIndexAndField() {
        FieldViolation violation = window.check(NOW.minus(Duration.ofDays(7)).minusMillis(1), NOW, 3, "frames[3].capturedAt")
                .orElseThrow();

        assertThat(violation.code()).isEqualTo(ErrorCodes.TIMESTAMP_TOO_OLD);
        assertThat(violation.index()).isEqualTo(3);
        assertThat(violation.field()).isEqualTo("frames[3].capturedAt");
    }
}
