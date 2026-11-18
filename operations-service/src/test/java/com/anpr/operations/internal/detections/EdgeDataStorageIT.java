package com.anpr.operations.internal.detections;

import com.anpr.operations.TestcontainersConfiguration;
import com.anpr.operations.internal.detections.DetectionService.NewDetection;
import com.anpr.operations.internal.devices.DeviceNotPairedException;
import com.anpr.operations.internal.devices.DevicePairingService;
import com.anpr.operations.internal.locations.DeviceLocationService.NewDeviceLocation;
import com.anpr.operations.internal.locations.DeviceLocationService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@SpringBootTest
@ActiveProfiles("test")
@Import(TestcontainersConfiguration.class)
class EdgeDataStorageIT {
    private static final OffsetDateTime AT = OffsetDateTime.of(2026, 10, 30, 9, 14, 22, 0, ZoneOffset.UTC);

    @Autowired private DetectionService detectionService;
    @Autowired private DeviceLocationService deviceLocationService;
    @Autowired private DevicePairingService pairingService;
    @Autowired private JdbcTemplate jdbc;

    @Test
    void detectionIsStoredWithTheOwnerAndTheExactPosition() {
        UUID owner = UUID.randomUUID();
        UUID device = pairedDevice(owner);
        UUID detectionId = UUID.randomUUID();

        detectionService.store(device, List.of(detection(detectionId)));

        String row = jdbc.queryForObject("""
                SELECT account_id || ' ' || ST_Y(position::geometry) || ' ' || ST_X(position::geometry)
                FROM detections WHERE detection_id = ?
                """, String.class, detectionId);
        assertThat(row).isEqualTo(owner + " 52.229676 21.012229");
    }

    @Test
    void theSameBatchTwiceStoresEveryDetectionOnce() {
        UUID device = pairedDevice(UUID.randomUUID());
        List<NewDetection> batch = List.of(detection(UUID.randomUUID()), detection(UUID.randomUUID()));

        detectionService.store(device, batch);
        detectionService.store(device, batch);

        assertThat(countOf("detections", device)).isEqualTo(2);
    }

    @Test
    void dataOfADeviceWithNoOwnerIsRejectedAndNothingIsStored() {
        UUID device = UUID.randomUUID();

        assertThatThrownBy(() -> detectionService.store(device, List.of(detection(UUID.randomUUID()))))
                .isInstanceOf(DeviceNotPairedException.class);
        assertThat(countOf("detections", device)).isZero();
    }

    @Test
    void aFailingDetectionRollsBackTheWholeBatch() {
        UUID device = pairedDevice(UUID.randomUUID());
        // A plate longer than the column fails in the database after the first detection was inserted.
        NewDetection tooLong = new NewDetection(UUID.randomUUID(), "WA123456789", AT, 52.2, 21.0, 0.9, 0.8, "images/x.jpg");

        assertThatThrownBy(() -> detectionService.store(device, List.of(detection(UUID.randomUUID()), tooLong)));
        assertThat(countOf("detections", device)).isZero();
    }

    @Test
    void theSameLocationsTwiceAreStoredOnce() {
        UUID device = pairedDevice(UUID.randomUUID());
        List<NewDeviceLocation> batch = List.of(
                new NewDeviceLocation(UUID.randomUUID(), AT, 52.229676, 21.012229),
                new NewDeviceLocation(UUID.randomUUID(), AT.plusSeconds(1), 52.229681, 21.012431));

        deviceLocationService.store(device, batch);
        deviceLocationService.store(device, batch);

        assertThat(countOf("device_locations", device)).isEqualTo(2);
    }

    private UUID pairedDevice(UUID owner) {
        UUID device = UUID.randomUUID();
        pairingService.pair(device, owner, 1);
        return device;
    }

    private static NewDetection detection(UUID detectionId) {
        return new NewDetection(detectionId, "WA12345", AT, 52.229676, 21.012229, 0.94, 0.88,
                "images/" + detectionId + ".jpg");
    }

    private int countOf(String table, UUID device) {
        return jdbc.queryForObject("SELECT count(*) FROM " + table + " WHERE device_id = ?", Integer.class, device);
    }
}
