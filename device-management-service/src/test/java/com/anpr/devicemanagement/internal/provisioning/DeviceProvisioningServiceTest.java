package com.anpr.devicemanagement.internal.provisioning;

import com.anpr.devicemanagement.internal.configuration.DefaultSettings;
import com.anpr.devicemanagement.internal.configuration.DeviceConfiguration;
import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.devices.DeviceRepository;
import com.anpr.devicemanagement.shared.error.ConflictException;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.ForbiddenException;
import com.anpr.devicemanagement.shared.error.NotFoundException;
import com.anpr.devicemanagement.shared.security.Caller;
import com.anpr.devicemanagement.support.TestData;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DeviceProvisioningServiceTest {

    private static final UUID DEVICE_ID = UUID.fromString("7d3f2c1e-0000-4000-8000-000000000000");
    private static final UUID ACCOUNT_ID = UUID.fromString("d1c2a0f8-0000-4000-8000-000000000000");
    private static final Instant NOW = Instant.parse("2026-11-02T10:00:00Z");
    private static final Caller ADMIN = new Caller.IamCaller("arn:aws:sts::000000000000:assumed-role/Admin/someone");
    private static final NewDevice REQUEST = new NewDevice(ACCOUNT_ID, "rpi-01", "Secret-password-1");

    @Mock
    private AccountDirectory accounts;
    @Mock
    private DeviceRepository devices;
    @Mock
    private DeviceRecords records;
    @Mock
    private DeviceEvents events;

    private DeviceProvisioningService service;

    @BeforeEach
    void setUp() {
        DefaultSettings defaults = mock(DefaultSettings.class);
        lenient().when(defaults.newSettings()).thenAnswer(invocation -> TestData.settings(60));
        service = new DeviceProvisioningService(accounts, devices, records, events, defaults, Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @Test
    void createsTheAccountThenTheRecordsThenAnnouncesThePairing() {
        givenAPersonWithoutDevice();
        when(accounts.createDevice("rpi-01", "Secret-password-1")).thenReturn(DEVICE_ID);

        Device device = service.create(ADMIN, REQUEST);

        assertThat(device.getDeviceId()).isEqualTo(DEVICE_ID);
        assertThat(device.getAccountId()).isEqualTo(ACCOUNT_ID);
        assertThat(device.getVersion()).isEqualTo(1L);
        ArgumentCaptor<DeviceConfiguration> configuration = ArgumentCaptor.forClass(DeviceConfiguration.class);
        InOrder order = inOrder(accounts, records, events);
        order.verify(accounts).createDevice("rpi-01", "Secret-password-1");
        order.verify(records).insert(any(Device.class), configuration.capture());
        order.verify(events).paired(DEVICE_ID, ACCOUNT_ID, 1L);
        assertThat(configuration.getValue().getDeviceId()).isEqualTo(DEVICE_ID);
        assertThat(configuration.getValue().getSettings()).isNotNull();
    }

    @Test
    void theOwnerMustBeAPerson() {
        when(accounts.isPerson(ACCOUNT_ID)).thenReturn(false);

        assertThatThrownBy(() -> service.create(ADMIN, REQUEST))
                .isInstanceOf(NotFoundException.class)
                .hasFieldOrPropertyWithValue("code", ErrorCodes.ACCOUNT_NOT_FOUND);
        verify(accounts, never()).createDevice(anyString(), anyString());
    }

    @Test
    void anAccountHasOneDeviceAtMost() {
        when(accounts.isPerson(ACCOUNT_ID)).thenReturn(true);
        when(devices.findByAccountId(ACCOUNT_ID)).thenReturn(Optional.of(Device.register(UUID.randomUUID(), ACCOUNT_ID, "rpi-00", NOW)));

        assertThatThrownBy(() -> service.create(ADMIN, REQUEST))
                .isInstanceOf(ConflictException.class)
                .hasFieldOrPropertyWithValue("code", ErrorCodes.ACCOUNT_HAS_DEVICE);
        verify(accounts, never()).createDevice(anyString(), anyString());
    }

    @Test
    void aFailedWriteDeletesTheAccountAgain() {
        givenAPersonWithoutDevice();
        when(accounts.createDevice("rpi-01", "Secret-password-1")).thenReturn(DEVICE_ID);
        RuntimeException failure = new RuntimeException("DynamoDB unavailable");
        doThrow(failure).when(records).insert(any(), any());

        assertThatThrownBy(() -> service.create(ADMIN, REQUEST)).isSameAs(failure);
        verify(accounts).deleteDevice("rpi-01");
        verify(events, never()).paired(any(), any(), anyLong());
    }

    @Test
    void aFailedPublishUndoesTheRecordsAndTheAccount() {
        givenAPersonWithoutDevice();
        when(accounts.createDevice("rpi-01", "Secret-password-1")).thenReturn(DEVICE_ID);
        RuntimeException failure = new RuntimeException("SNS unavailable");
        doThrow(failure).when(events).paired(DEVICE_ID, ACCOUNT_ID, 1L);

        assertThatThrownBy(() -> service.create(ADMIN, REQUEST)).isSameAs(failure);
        verify(records).remove(DEVICE_ID);
        verify(accounts).deleteDevice("rpi-01");
    }

    @Test
    void aFailingUndoStepDoesNotStopTheNextOneNorHideTheCause() {
        givenAPersonWithoutDevice();
        when(accounts.createDevice("rpi-01", "Secret-password-1")).thenReturn(DEVICE_ID);
        RuntimeException failure = new RuntimeException("SNS unavailable");
        doThrow(failure).when(events).paired(DEVICE_ID, ACCOUNT_ID, 1L);
        doThrow(new RuntimeException("DynamoDB unavailable")).when(records).remove(DEVICE_ID);

        assertThatThrownBy(() -> service.create(ADMIN, REQUEST))
                .isSameAs(failure)
                .satisfies(e -> assertThat(e.getSuppressed()).hasSize(1));
        verify(accounts).deleteDevice("rpi-01");
    }

    @Test
    void deletesTheAccountThenAnnouncesThenDeletesTheRecords() {
        when(devices.findById(DEVICE_ID)).thenReturn(Optional.of(Device.register(DEVICE_ID, ACCOUNT_ID, "rpi-01", NOW)));

        service.delete(ADMIN, DEVICE_ID);

        InOrder order = inOrder(accounts, events, records);
        order.verify(accounts).deleteDevice("rpi-01");
        order.verify(events).unpaired(DEVICE_ID, 2L);
        order.verify(records).remove(DEVICE_ID);
    }

    @Test
    void aFailedPublishKeepsTheRecordsSoTheDeletionCanBeRepeated() {
        when(devices.findById(DEVICE_ID)).thenReturn(Optional.of(Device.register(DEVICE_ID, ACCOUNT_ID, "rpi-01", NOW)));
        doThrow(new RuntimeException("SNS unavailable")).when(events).unpaired(DEVICE_ID, 2L);

        assertThatThrownBy(() -> service.delete(ADMIN, DEVICE_ID)).isInstanceOf(RuntimeException.class);
        verify(records, never()).remove(any());
    }

    @Test
    void deletingAnUnknownDeviceIsNotFound() {
        when(devices.findById(DEVICE_ID)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.delete(ADMIN, DEVICE_ID))
                .isInstanceOf(NotFoundException.class)
                .hasFieldOrPropertyWithValue("code", ErrorCodes.DEVICE_NOT_FOUND);
        verifyNoInteractions(accounts, events, records);
    }

    @Test
    void onlyAnAdministratorProvisions() {
        Caller person = new Caller.UserCaller(ACCOUNT_ID);

        assertThatThrownBy(() -> service.create(person, REQUEST)).isInstanceOf(ForbiddenException.class);
        assertThatThrownBy(() -> service.delete(person, DEVICE_ID)).isInstanceOf(ForbiddenException.class);
        verifyNoInteractions(accounts, devices, records, events);
    }

    @Test
    void thePasswordNeverAppearsInTheRequestText() {
        assertThat(REQUEST.toString()).doesNotContain("Secret-password-1").contains("rpi-01");
    }

    private void givenAPersonWithoutDevice() {
        when(accounts.isPerson(ACCOUNT_ID)).thenReturn(true);
        when(devices.findByAccountId(ACCOUNT_ID)).thenReturn(Optional.empty());
    }
}
