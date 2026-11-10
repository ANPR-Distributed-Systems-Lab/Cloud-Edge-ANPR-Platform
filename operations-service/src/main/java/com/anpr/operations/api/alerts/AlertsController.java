package com.anpr.operations.api.alerts;

import com.anpr.operations.api.generated.AlertsApi;
import com.anpr.operations.api.generated.model.*;
import com.anpr.operations.internal.alerts.AlertService;
import com.anpr.operations.internal.alerts.model.Alert;
import com.anpr.operations.internal.alerts.model.AlertFilter;
import com.anpr.operations.shared.security.CurrentAccount;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;

@RestController
@RequiredArgsConstructor
public class AlertsController implements AlertsApi {
    private final AlertService alertService;
    private final AlertApiMapper mapper;
    private final CurrentAccount currentAccount;

    @Override
    public ResponseEntity<AlertResponse> createAlert(CreateAlertRequest request) {
        Alert alert = alertService.create(request.getPlate(), request.getAlertText());
        URI location = URI.create("/api/v1/alerts/" + alert.getAlertId());
        return ResponseEntity.created(location).body(mapper.toResponse(alert));
    }

    @Override
    public ResponseEntity<AlertResponse> getAlert(UUID alertId) {
        return ResponseEntity.ok(mapper.toResponse(alertService.get(alertId)));
    }

    @Override
    public ResponseEntity<AlertPage> listAlerts(Integer page, Integer size, AlertSortField sort, SortDirection direction,
                                                String plate, OffsetDateTime from, OffsetDateTime to,
                                                String ifNoneMatch) {
        if (currentAccount.isDevice()) {
            List<Alert> alerts = alertService.listForDevice();
            // Spring compares this ETag with If-None-Match itself and answers 304 with no body when they match.
            return ResponseEntity.ok().eTag(AlertListETag.of(alerts)).body(mapper.toDevicePage(alerts));
        }
        PageRequest pageable = PageRequest.of(page, size, toSort(sort, direction));
        return ResponseEntity.ok(mapper.toPage(alertService.list(new AlertFilter(plate, from, to), pageable)));
    }

    @Override
    public ResponseEntity<AlertResponse> updateAlert(UUID alertId, UpdateAlertRequest request) {
        Alert alert = alertService.update(alertId, request.getAlertText(), request.getVersion());
        return ResponseEntity.ok(mapper.toResponse(alert));
    }

    @Override
    public ResponseEntity<Void> deleteAlert(UUID alertId) {
        alertService.delete(alertId);
        return ResponseEntity.noContent().build();
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
