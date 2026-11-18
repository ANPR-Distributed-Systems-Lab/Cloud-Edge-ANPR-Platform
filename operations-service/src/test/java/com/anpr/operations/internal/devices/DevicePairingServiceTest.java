package com.anpr.operations.internal.devices;

import com.anpr.operations.internal.accounts.AccountRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class DevicePairingServiceTest {

    private static final UUID DEVICE_ID = UUID.fromString("22222222-2222-2222-2222-222222222222");
    private static final UUID ACCOUNT_ID = UUID.fromString("11111111-1111-1111-1111-111111111111");
    private static final UUID OTHER_ACCOUNT_ID = UUID.fromString("33333333-3333-3333-3333-333333333333");

    @Mock
    private DeviceRepository deviceRepository;

    @Mock
    private AccountRepository accountRepository;

    private DevicePairingService service;

    @BeforeEach
    void setUp() {
        service = new DevicePairingService(deviceRepository, accountRepository);
    }

    @Test
    void pairNewDeviceSavesItWithItsAccount() {
        when(deviceRepository.findById(DEVICE_ID)).thenReturn(Optional.empty());

        service.pair(DEVICE_ID, ACCOUNT_ID, 1);

        verify(accountRepository).insertIfAbsent(ACCOUNT_ID);
        ArgumentCaptor<Device> saved = ArgumentCaptor.forClass(Device.class);
        verify(deviceRepository).save(saved.capture());
        assertThat(saved.getValue().getAccountId()).isEqualTo(ACCOUNT_ID);
        assertThat(saved.getValue().getVersion()).isEqualTo(1);
    }

    @Test
    void pairWithNewerVersionChangesOwner() {
        Device device = Device.paired(DEVICE_ID, ACCOUNT_ID, 1);
        when(deviceRepository.findById(DEVICE_ID)).thenReturn(Optional.of(device));

        service.pair(DEVICE_ID, OTHER_ACCOUNT_ID, 2);

        assertThat(device.getAccountId()).isEqualTo(OTHER_ACCOUNT_ID);
        assertThat(device.getVersion()).isEqualTo(2);
        verify(accountRepository).insertIfAbsent(OTHER_ACCOUNT_ID);
    }

    @Test
    void duplicatePairIsIgnored() {
        Device device = Device.paired(DEVICE_ID, ACCOUNT_ID, 1);
        when(deviceRepository.findById(DEVICE_ID)).thenReturn(Optional.of(device));

        service.pair(DEVICE_ID, ACCOUNT_ID, 1);

        assertThat(device.getVersion()).isEqualTo(1);
        verify(accountRepository, never()).insertIfAbsent(any());
        verify(deviceRepository, never()).save(any());
    }

    @Test
    void unpairClearsOwnerAndKeepsVersion() {
        Device device = Device.paired(DEVICE_ID, ACCOUNT_ID, 1);
        when(deviceRepository.findById(DEVICE_ID)).thenReturn(Optional.of(device));

        service.unpair(DEVICE_ID, 2);

        assertThat(device.getAccountId()).isNull();
        assertThat(device.getVersion()).isEqualTo(2);
    }

    @Test
    void unpairBeforePairRemembersVersion() {
        when(deviceRepository.findById(DEVICE_ID)).thenReturn(Optional.empty());

        service.unpair(DEVICE_ID, 2);

        ArgumentCaptor<Device> saved = ArgumentCaptor.forClass(Device.class);
        verify(deviceRepository).save(saved.capture());
        assertThat(saved.getValue().getAccountId()).isNull();
        assertThat(saved.getValue().getVersion()).isEqualTo(2);
    }

    @Test
    void latePairAfterUnpairIsIgnored() {
        Device device = Device.unpaired(DEVICE_ID, 2);
        when(deviceRepository.findById(DEVICE_ID)).thenReturn(Optional.of(device));

        service.pair(DEVICE_ID, ACCOUNT_ID, 1);

        assertThat(device.getAccountId()).isNull();
        assertThat(device.getVersion()).isEqualTo(2);
        verify(accountRepository, never()).insertIfAbsent(any());
    }
}