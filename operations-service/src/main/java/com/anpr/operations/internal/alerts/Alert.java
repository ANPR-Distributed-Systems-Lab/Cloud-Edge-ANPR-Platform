package com.anpr.operations.internal.alerts;

import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;
import java.util.UUID;

import java.time.OffsetDateTime;

@Entity
@Table(name = "alerts")
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Alert {
    @Id
    private UUID alertId;
    private UUID accountId;
    private String plate;
    private String alertText;
    private OffsetDateTime createdAt;
    private OffsetDateTime lastDetectedAt;
    @Version
    private Long version;
    public static Alert create(UUID accountId, String plate, String alertText, OffsetDateTime now) {
        Alert alert = new Alert();
        alert.alertId = UUID.randomUUID();
        alert.accountId = accountId;
        alert.plate = plate;
        alert.alertText = alertText;
        alert.createdAt = now;

        return alert;
    }

    public void update(String plate, String alertText) {
        this.plate = plate;
        this.alertText = alertText;
    }
}
