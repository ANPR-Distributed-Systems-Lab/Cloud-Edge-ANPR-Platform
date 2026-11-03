package com.anpr.devicemanagement.internal.metrics;

import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.devices.DeviceLookup;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.FieldViolation;
import com.anpr.devicemanagement.shared.error.ForbiddenException;
import com.anpr.devicemanagement.shared.error.ValidationException;
import com.anpr.devicemanagement.shared.security.Caller;
import com.anpr.devicemanagement.support.TestData;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.InstanceOfAssertFactories.list;
import static org.assertj.core.groups.Tuple.tuple;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class MetricsServiceTest {

    private static final UUID DEVICE_ID = UUID.fromString("7d3f2c1e-0000-4000-8000-000000000000");
    private static final UUID ACCOUNT_ID = UUID.fromString("d1c2a0f8-0000-4000-8000-000000000000");
    private static final Instant NOW = Instant.parse("2026-11-02T10:00:00Z");
    private static final Duration RETENTION = Duration.ofDays(7);
    private static final Duration SKEW = Duration.ofMinutes(5);
    private static final Caller DEVICE = new Caller.DeviceCaller(DEVICE_ID);
    private static final Caller OWNER = new Caller.UserCaller(ACCOUNT_ID);

    @Mock
    private DeviceLookup deviceLookup;
    @Mock
    private MeasurementRepository measurements;

    private MetricsService service;

    @BeforeEach
    void setUp() {
        service = new MetricsService(deviceLookup, measurements, new MetricsProperties(RETENTION, SKEW),
                Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void storesTheBatchForTheCallingDeviceWithItsExpiry() {
        when(deviceLookup.deviceOf(DEVICE)).thenReturn(device());
        Measurement measurement = TestData.measurement(NOW.minusSeconds(60));

        service.report(DEVICE, List.of(measurement));

        verify(measurements).saveAll(List.of(measurement));
        assertThat(measurement.getDeviceId()).isEqualTo(DEVICE_ID);
        assertThat(measurement.getExpiresAt()).isEqualTo(NOW.minusSeconds(60).plus(RETENTION).getEpochSecond());
    }

    @Test
    void refusesTheWholeBatchListingEveryBadMeasurement() {
        when(deviceLookup.deviceOf(DEVICE)).thenReturn(device());
        List<Measurement> batch = List.of(
                TestData.measurement(NOW.minusSeconds(120)),
                TestData.measurement(NOW.plus(SKEW).plusSeconds(1)),
                TestData.measurement(NOW.minus(RETENTION).minusSeconds(1)),
                TestData.measurement(NOW.minusSeconds(120)));

        assertThatThrownBy(() -> service.report(DEVICE, batch))
                .isInstanceOf(ValidationException.class)
                .extracting(e -> ((ValidationException) e).getViolations(), list(FieldViolation.class))
                .extracting(FieldViolation::index, FieldViolation::code)
                .containsExactly(
                        tuple(1, ErrorCodes.TIMESTAMP_IN_FUTURE),
                        tuple(2, ErrorCodes.TIMESTAMP_TOO_OLD),
                        tuple(3, ErrorCodes.DUPLICATE_RECORDED_AT));
        verify(measurements, never()).saveAll(anyList());
    }

    @Test
    void aPersonMayNotReportMetrics() {
        assertThatThrownBy(() -> service.report(OWNER, List.of(TestData.measurement(NOW))))
                .isInstanceOf(ForbiddenException.class);
        verifyNoInteractions(deviceLookup, measurements);
    }

    @Test
    void theOwnerGetsTheLatestMeasurementsOldestFirst() {
        Measurement older = TestData.measurement(NOW.minusSeconds(120));
        Measurement newer = TestData.measurement(NOW.minusSeconds(60));
        when(deviceLookup.deviceOf(OWNER)).thenReturn(device());
        when(measurements.findLatest(DEVICE_ID, NOW.minus(RETENTION), NOW.plus(SKEW).plusMillis(1), 2))
                .thenReturn(List.of(newer, older));

        MetricsService.DeviceMeasurements result = service.latest(OWNER, 2, null);

        assertThat(result.deviceId()).isEqualTo(DEVICE_ID);
        assertThat(result.measurements()).containsExactly(older, newer);
    }

    @Test
    void beforeIsTheUpperBoundOfTheQuery() {
        Instant before = NOW.minusSeconds(3600);
        when(deviceLookup.deviceOf(OWNER)).thenReturn(device());
        when(measurements.findLatest(DEVICE_ID, NOW.minus(RETENTION), before, 100)).thenReturn(List.of());

        assertThat(service.latest(OWNER, 100, before).measurements()).isEmpty();
    }

    @Test
    void aDeviceMayNotReadTheChart() {
        assertThatThrownBy(() -> service.latest(DEVICE, 100, null)).isInstanceOf(ForbiddenException.class);
        verify(measurements, never()).findLatest(any(), any(), any(), anyInt());
    }

    private static Device device() {
        return Device.register(DEVICE_ID, ACCOUNT_ID, "rpi-01", NOW);
    }
}
