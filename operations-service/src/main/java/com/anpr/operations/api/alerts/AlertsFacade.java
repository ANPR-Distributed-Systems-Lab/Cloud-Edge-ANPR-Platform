package com.anpr.operations.api.alerts;

import com.anpr.operations.api.generated.model.AlertPage;
import com.anpr.operations.api.generated.model.AlertResponse;
import com.anpr.operations.api.generated.model.AlertSortField;
import com.anpr.operations.api.generated.model.SortDirection;
import com.anpr.operations.internal.alerts.AlertService;
import com.anpr.operations.internal.alerts.model.Alert;
import com.anpr.operations.internal.alerts.model.AlertFilter;
import com.anpr.operations.internal.alerts.repository.AlertVersion;
import com.anpr.operations.shared.time.TimeRange;
import com.anpr.operations.shared.security.CurrentAccount;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.OffsetDateTime;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * Alert endpoints between the controller and AlertService: picks the person or device variant of the list, builds
 * sorting, the device list ETag and the HTTP response. AlertsController only calls this class.
 */
@Component
@RequiredArgsConstructor
public class AlertsFacade {
    private final AlertService alertService;
    private final AlertApiMapper mapper;
    private final CurrentAccount currentAccount;

    public ResponseEntity<AlertResponse> create(String plate, String alertText) {
        Alert alert = alertService.create(plate, alertText);
        URI location = URI.create("/api/v1/alerts/" + alert.getAlertId());
        return ResponseEntity.created(location).body(mapper.toResponse(alert));
    }

    public ResponseEntity<AlertResponse> get(UUID alertId) {
        return ResponseEntity.ok(mapper.toResponse(alertService.get(alertId)));
    }

    /** A device gets every alert of its owner with an ETag; a person gets one page and no ETag (GET /alerts). */
    public ResponseEntity<AlertPage> list(int page, int size, AlertSortField sort, SortDirection direction,
                                          String plate, OffsetDateTime from, OffsetDateTime to, String ifNoneMatch) {
        if (currentAccount.isDevice()) {
            // Devices poll and the list rarely changes: compare ids and versions first, load the alerts only on change.
            String current = eTagOf(alertService.versionsForDevice().stream()
                    .collect(Collectors.toMap(AlertVersion::getAlertId, AlertVersion::getVersion)));
            if (matches(ifNoneMatch, current)) {
                return ResponseEntity.status(HttpStatus.NOT_MODIFIED).eTag(current).build();
            }
            List<Alert> alerts = alertService.listForDevice();
            // The ETag of the loaded list, so it always describes the body even if an alert changed in between.
            String eTag = eTagOf(alerts.stream().collect(Collectors.toMap(Alert::getAlertId, Alert::getVersion)));
            return ResponseEntity.ok().eTag(eTag).body(mapper.toDevicePage(alerts));
        }
        PageRequest pageable = PageRequest.of(page, size, toSort(sort, direction));
        AlertFilter filter = new AlertFilter(plate, new TimeRange(from, to));
        return ResponseEntity.ok(mapper.toPage(alertService.list(filter, pageable)));
    }

    public ResponseEntity<AlertResponse> update(UUID alertId, String alertText, long version) {
        return ResponseEntity.ok(mapper.toResponse(alertService.update(alertId, alertText, version)));
    }

    public ResponseEntity<Void> delete(UUID alertId) {
        alertService.delete(alertId);
        return ResponseEntity.noContent().build();
    }

    /**
     * Weak ETag of the device alert list, built from the id and version of every alert: it changes when an alert is
     * added, updated or deleted, and not when lastDetectedAt moves (operations-api.yaml, GET /alerts).
     */
    static String eTagOf(Map<UUID, Long> versionsById) {
        MessageDigest digest = sha256();
        new TreeMap<>(versionsById).forEach((alertId, version) ->
                digest.update((alertId + ":" + version + ";").getBytes(StandardCharsets.UTF_8)));
        // 128 bits are plenty to tell two versions of one list apart.
        return "W/\"" + HexFormat.of().formatHex(digest.digest(), 0, 16) + "\"";
    }

    /** If-None-Match may hold several tags or "*"; weak and strong forms of one tag match (RFC 9110, 13.1.2). */
    static boolean matches(String ifNoneMatch, String eTag) {
        if (ifNoneMatch == null) {
            return false;
        }
        for (String candidate : ifNoneMatch.split(",")) {
            String tag = candidate.trim();
            if (tag.equals("*") || opaque(tag).equals(opaque(eTag))) {
                return true;
            }
        }
        return false;
    }

    private static String opaque(String tag) {
        return tag.startsWith("W/") ? tag.substring(2) : tag;
    }

    private static MessageDigest sha256() {
        try {
            return MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 is required by every Java runtime", e);
        }
    }

    private static Sort toSort(AlertSortField field, SortDirection direction) {
        String property = switch (field) {
            case CREATED_AT -> "createdAt";
            case LAST_DETECTED_AT -> "lastDetectedAt";
        };
        Sort.Order order = new Sort.Order(Sort.Direction.valueOf(direction.name()), property).nullsLast();
        // Never detected plates go last in both directions; the id keeps the order stable between pages.
        return Sort.by(order).and(Sort.by("alertId"));
    }
}
