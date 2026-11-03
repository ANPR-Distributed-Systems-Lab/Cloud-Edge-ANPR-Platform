package com.anpr.devicemanagement.internal.devices;

import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.ForbiddenException;
import com.anpr.devicemanagement.shared.error.NotFoundException;
import com.anpr.devicemanagement.shared.security.Caller;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DeviceLookupTest {

    private static final UUID DEVICE_ID = UUID.fromString("7d3f2c1e-0000-4000-8000-000000000000");
    private static final UUID ACCOUNT_ID = UUID.fromString("d1c2a0f8-0000-4000-8000-000000000000");
    private static final Device DEVICE = Device.register(DEVICE_ID, ACCOUNT_ID, "rpi-01", Instant.EPOCH);

    @Mock
    private DeviceRepository devices;

    @InjectMocks
    private DeviceLookup lookup;

    @Test
    void aDeviceFindsItselfById() {
        when(devices.findById(DEVICE_ID)).thenReturn(Optional.of(DEVICE));

        assertThat(lookup.deviceOf(new Caller.DeviceCaller(DEVICE_ID))).isSameAs(DEVICE);
    }

    @Test
    void aPersonFindsTheDeviceOfTheirAccount() {
        when(devices.findByAccountId(ACCOUNT_ID)).thenReturn(Optional.of(DEVICE));

        assertThat(lookup.deviceOf(new Caller.UserCaller(ACCOUNT_ID))).isSameAs(DEVICE);
    }

    @Test
    void anUnregisteredDeviceOrAPersonWithoutDeviceIsNotFound() {
        when(devices.findById(DEVICE_ID)).thenReturn(Optional.empty());
        when(devices.findByAccountId(ACCOUNT_ID)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> lookup.deviceOf(new Caller.DeviceCaller(DEVICE_ID)))
                .isInstanceOf(NotFoundException.class)
                .hasFieldOrPropertyWithValue("code", ErrorCodes.DEVICE_NOT_FOUND);
        assertThatThrownBy(() -> lookup.deviceOf(new Caller.UserCaller(ACCOUNT_ID)))
                .isInstanceOf(NotFoundException.class);
    }

    @Test
    void anAdministratorHasNoDevice() {
        assertThatThrownBy(() -> lookup.deviceOf(new Caller.IamCaller("arn:aws:iam::0:user/admin")))
                .isInstanceOf(ForbiddenException.class);
        verifyNoInteractions(devices);
    }
}
