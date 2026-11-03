package com.anpr.devicemanagement.internal.overview;

import com.anpr.devicemanagement.internal.configuration.ConfigurationService;
import com.anpr.devicemanagement.internal.configuration.DeviceConfiguration;
import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.devices.DeviceLookup;
import com.anpr.devicemanagement.internal.metrics.MetricsService;
import com.anpr.devicemanagement.shared.security.Caller;
import com.anpr.devicemanagement.support.TestData;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DeviceOverviewServiceTest {

    private static final UUID DEVICE_ID = UUID.fromString("7d3f2c1e-0000-4000-8000-000000000000");
    private static final Instant NOW = Instant.parse("2026-11-02T10:00:00Z");
    private static final Caller OWNER = new Caller.UserCaller(UUID.randomUUID());
    private static final int METRICS_SECONDS = 60;

    @Mock
    private DeviceLookup deviceLookup;
    @Mock
    private MetricsService metrics;
    @Mock
    private ConfigurationService configurations;

    private DeviceOverviewService service;

    @BeforeEach
    void setUp() {
        service = new DeviceOverviewService(deviceLookup, metrics, configurations, new OverviewProperties(3),
                Clock.fixed(NOW, ZoneOffset.UTC));
        when(deviceLookup.deviceOf(OWNER)).thenReturn(Device.register(DEVICE_ID, UUID.randomUUID(), "rpi-01", NOW));
    }

    @Test
    void onlineWhileTheLastMeasurementIsYoungerThanThreeIntervals() {
        givenLastMeasurementAt(NOW.minusSeconds(3 * METRICS_SECONDS - 1));

        DeviceOverview overview = service.overviewOf(OWNER);

        assertThat(overview.online()).isTrue();
        assertThat(overview.lastMetricsAt()).isEqualTo(NOW.minusSeconds(3 * METRICS_SECONDS - 1));
    }

    @Test
    void offlineOnceThreeIntervalsPassed() {
        givenLastMeasurementAt(NOW.minusSeconds(3 * METRICS_SECONDS));

        assertThat(service.overviewOf(OWNER).online()).isFalse();
    }

    @Test
    void offlineWithoutAnyMeasurement() {
        when(metrics.lastMeasurement(DEVICE_ID)).thenReturn(Optional.empty());

        DeviceOverview overview = service.overviewOf(OWNER);

        assertThat(overview.online()).isFalse();
        assertThat(overview.lastMetricsAt()).isNull();
    }

    private void givenLastMeasurementAt(Instant recordedAt) {
        when(metrics.lastMeasurement(DEVICE_ID)).thenReturn(Optional.of(TestData.measurement(recordedAt)));
        when(configurations.get(DEVICE_ID))
                .thenReturn(DeviceConfiguration.initial(DEVICE_ID, TestData.settings(METRICS_SECONDS), NOW));
    }
}
