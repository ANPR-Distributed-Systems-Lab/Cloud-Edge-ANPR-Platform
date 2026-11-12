package com.anpr.devicemanagement.internal.configuration;

import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.devices.DeviceLookup;
import com.anpr.devicemanagement.internal.models.PublishedModels;
import com.anpr.devicemanagement.shared.error.ConflictException;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.ForbiddenException;
import com.anpr.devicemanagement.shared.error.TechnicalException;
import com.anpr.devicemanagement.shared.error.ValidationException;
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
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ConfigurationServiceTest {

    private static final UUID DEVICE_ID = UUID.fromString("7d3f2c1e-0000-4000-8000-000000000000");
    private static final UUID ACCOUNT_ID = UUID.fromString("d1c2a0f8-0000-4000-8000-000000000000");
    private static final Instant NOW = Instant.parse("2026-11-02T10:00:00Z");
    private static final Caller OWNER = new Caller.UserCaller(ACCOUNT_ID);

    @Mock
    private DeviceLookup deviceLookup;
    @Mock
    private DeviceConfigurationRepository configurations;
    @Mock
    private PublishedModels publishedModels;

    private ConfigurationService service;

    @BeforeEach
    void setUp() {
        service = new ConfigurationService(deviceLookup, configurations, publishedModels, Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void theOwnerReplacesTheSettingsOfTheVersionTheyRead() {
        DeviceConfiguration stored = storedConfiguration(4L);
        when(deviceLookup.deviceOf(OWNER)).thenReturn(device());
        when(configurations.findByDeviceId(DEVICE_ID)).thenReturn(Optional.of(stored));
        when(configurations.update(stored)).thenReturn(stored);
        DeviceSettings newSettings = TestData.settings(30);

        DeviceConfiguration result = service.update(OWNER, 4L, newSettings);

        assertThat(result.getSettings()).isSameAs(newSettings);
        assertThat(result.getUpdatedAt()).isEqualTo(NOW);
    }

    @Test
    void aStaleVersionIsAConflictAndNothingIsWritten() {
        when(deviceLookup.deviceOf(OWNER)).thenReturn(device());
        when(configurations.findByDeviceId(DEVICE_ID)).thenReturn(Optional.of(storedConfiguration(5L)));

        assertThatThrownBy(() -> service.update(OWNER, 4L, TestData.settings(30)))
                .isInstanceOf(ConflictException.class)
                .hasFieldOrPropertyWithValue("code", ErrorCodes.CONCURRENT_MODIFICATION);
        verify(configurations, never()).update(any());
    }

    @Test
    void aModelVersionThatIsNotPublishedIsRefusedAndNothingIsWritten() {
        when(deviceLookup.deviceOf(OWNER)).thenReturn(device());
        when(configurations.findByDeviceId(DEVICE_ID)).thenReturn(Optional.of(storedConfiguration(4L)));
        DeviceSettings newSettings = TestData.settings(30);
        doThrow(new ValidationException(List.of())).when(publishedModels).requirePublished(newSettings.getModels());

        assertThatThrownBy(() -> service.update(OWNER, 4L, newSettings)).isInstanceOf(ValidationException.class);
        verify(configurations, never()).update(any());
    }

    @Test
    void aDeviceMayNotEditItsConfiguration() {
        assertThatThrownBy(() -> service.update(new Caller.DeviceCaller(DEVICE_ID), 1L, TestData.settings(30)))
                .isInstanceOf(ForbiddenException.class);
        verify(configurations, never()).update(any());
    }

    @Test
    void aDeviceReadsItsConfiguration() {
        Caller device = new Caller.DeviceCaller(DEVICE_ID);
        DeviceConfiguration stored = storedConfiguration(1L);
        when(deviceLookup.deviceOf(device)).thenReturn(device());
        when(configurations.findByDeviceId(DEVICE_ID)).thenReturn(Optional.of(stored));

        assertThat(service.get(device)).isSameAs(stored);
    }

    @Test
    void aMissingConfigurationOfARegisteredDeviceIsOurFault() {
        when(configurations.findByDeviceId(DEVICE_ID)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.get(DEVICE_ID)).isInstanceOf(TechnicalException.class);
    }

    private static Device device() {
        return Device.register(DEVICE_ID, ACCOUNT_ID, "rpi-01", NOW);
    }

    private static DeviceConfiguration storedConfiguration(long version) {
        DeviceConfiguration configuration = DeviceConfiguration.initial(DEVICE_ID, TestData.settings(60), Instant.EPOCH);
        configuration.setVersion(version);
        return configuration;
    }
}
