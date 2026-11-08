package com.anpr.operations.api.alerts;

import com.anpr.operations.internal.alerts.model.Alert;
import lombok.NoArgsConstructor;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;

import static lombok.AccessLevel.PRIVATE;

/**
 * Weak ETag of the alert list of a device. Built from the id and version of every alert, so it changes when an alert
 * is added, updated or deleted, and not when lastDetectedAt moves (operations-api.yaml, GET /alerts).
 */
@NoArgsConstructor(access = PRIVATE)
final class AlertListETag {

    static String of(List<Alert> alerts) {
        MessageDigest digest = sha256();
        alerts.stream()
                .sorted(Comparator.comparing(Alert::getAlertId))
                .forEach(alert -> digest.update(
                        (alert.getAlertId() + ":" + alert.getVersion() + ";").getBytes(StandardCharsets.UTF_8)));
        // 128 bits are plenty to tell two versions of one list apart.
        return "W/\"" + HexFormat.of().formatHex(digest.digest(), 0, 16) + "\"";
    }

    private static MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e){
            throw new IllegalStateException("SHA-256 is required by every Java runtime", e);
        }
    }
}
