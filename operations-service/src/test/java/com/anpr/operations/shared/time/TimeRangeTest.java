package com.anpr.operations.shared.time;

import com.anpr.operations.shared.error.BadRequestException;
import com.anpr.operations.shared.error.ErrorCodes;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatNoException;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class TimeRangeTest {
    private static final OffsetDateTime T0 = OffsetDateTime.parse("2026-10-01T00:00:00Z");

    @Test
    void toAfterFromIsAccepted() {
        assertThatNoException().isThrownBy(() -> new TimeRange(T0, T0.plusSeconds(1)));
    }

    @Test
    void eitherEndMayBeMissing() {
        assertThatNoException().isThrownBy(() -> new TimeRange(null, null));
        assertThatNoException().isThrownBy(() -> new TimeRange(T0, null));
        assertThatNoException().isThrownBy(() -> new TimeRange(null, T0));
    }

    @Test
    void toEqualToFromIsRejected() {
        assertThatThrownBy(() -> new TimeRange(T0, T0))
                .isInstanceOfSatisfying(BadRequestException.class,
                        e -> assertThat(e.getCode()).isEqualTo(ErrorCodes.INVALID_TIME_RANGE));
    }

    @Test
    void toBeforeFromIsRejected() {
        assertThatThrownBy(() -> new TimeRange(T0, T0.minusHours(1)))
                .isInstanceOf(BadRequestException.class);
    }

    @Test
    void isLongerThanOnlyWhenTheRangeExceedsTheLimit() {
        assertThat(new TimeRange(T0, T0.plusDays(7)).isLongerThan(Duration.ofDays(7))).isFalse();
        assertThat(new TimeRange(T0, T0.plusDays(7).plusNanos(1000)).isLongerThan(Duration.ofDays(7))).isTrue();
    }

    @Test
    void anOpenRangeIsNeverLongerThanTheLimit() {
        assertThat(new TimeRange(T0, null).isLongerThan(Duration.ofDays(7))).isFalse();
        assertThat(new TimeRange(null, T0).isLongerThan(Duration.ofDays(7))).isFalse();
    }
}
