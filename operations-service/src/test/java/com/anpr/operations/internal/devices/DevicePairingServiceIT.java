package com.anpr.operations.internal.devices;

import com.anpr.operations.TestcontainersConfiguration;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest
@Import(TestcontainersConfiguration.class)
@ActiveProfiles("test")
class DevicePairingServiceIT {

    @Autowired
    private DevicePairingService service;

    @Autowired
    private DeviceRepository deviceRepository;

    @Autowired
    private JdbcTemplate jdbc;

    @Test
    void theSamePairingTwiceStoresOneDeviceAndOneAccount() {
        UUID deviceId = UUID.randomUUID();
        UUID accountId = UUID.randomUUID();

        service.pair(deviceId, accountId, 1);
        service.pair(deviceId, accountId, 1);

        assertThat(count("SELECT count(*) FROM devices WHERE device_id = ?", deviceId)).isEqualTo(1);
        assertThat(count("SELECT count(*) FROM accounts WHERE account_id = ?", accountId)).isEqualTo(1);
    }

    @Test
    void unpairingIsStoredWithoutTheOwner() {
        UUID deviceId = UUID.randomUUID();
        service.pair(deviceId, UUID.randomUUID(), 1);

        service.unpair(deviceId, 2);

        Device stored = deviceRepository.findById(deviceId).orElseThrow();
        assertThat(stored.getAccountId()).isNull();
        assertThat(stored.getVersion()).isEqualTo(2);
    }

    @Test
    void lateStalePairingDoesNotLinkAnUnpairedDevice() {
        UUID deviceId = UUID.randomUUID();
        service.unpair(deviceId, 2);

        service.pair(deviceId, UUID.randomUUID(), 1);

        Device stored = deviceRepository.findById(deviceId).orElseThrow();
        assertThat(stored.getAccountId()).isNull();
        assertThat(stored.getVersion()).isEqualTo(2);
    }

    @Test
    void secondDeviceOfAnAccountIsRefusedWhileTheFirstIsStillLinked() {
        UUID accountId = UUID.randomUUID();
        service.pair(UUID.randomUUID(), accountId, 1);

        // The unpairing of the old device has not arrived yet: the event fails and SQS delivers it again later.
        assertThatThrownBy(() -> service.pair(UUID.randomUUID(), accountId, 1))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    private int count(String sql, UUID id) {
        return jdbc.queryForObject(sql, Integer.class, id);
    }
}