package com.anpr.operations.api.alerts;

import com.anpr.operations.api.generated.AlertsApi;
import com.anpr.operations.api.generated.model.*;
import com.anpr.operations.internal.alerts.Alert;
import com.anpr.operations.internal.alerts.AlertService;
import lombok.RequiredArgsConstructor;
import org.springframework.data.annotation.CreatedBy;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;
import java.util.UUID;

@RestController
@RequiredArgsConstructor
public class AlertsController implements AlertsApi {
    private final AlertService alertService;
    private final AlertApiMapper mapper;

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
    public ResponseEntity<AlertPage> listAlerts(Integer page, Integer size, AlertSortField sort, SortDirection direction) {
        PageRequest pageable = PageRequest.of(page, size, toSort(sort, direction));
        return ResponseEntity.ok(mapper.toPage(alertService.list(pageable)));
    }

    @Override
    public ResponseEntity<AlertResponse> updateAlert(UUID alertId, UpdateAlertRequest request) {
        Alert alert = alertService.update(alertId, request.getPlate(), request.getAlertText(), request.getVersion());
        return ResponseEntity.ok(mapper.toResponse(alert));
    }

    @Override
    public ResponseEntity<Void> deleteAlert(UUID alertId) {
        alertService.delete(alertId);
        return ResponseEntity.noContent().build();
    }

    @Override
    public ResponseEntity<DetectionPage> listAlertDetections(UUID alertId, Integer page, Integer size) {
        // Detections arrive with the SQS consumer (next stage).
        return ResponseEntity.status(HttpStatus.NOT_IMPLEMENTED).build();
    }


    private static Sort toSort(AlertSortField field, SortDirection direction) {
        String property = switch (field) {
            case CREATED_AT -> "createdAt";
            case LAST_DETECTED_AT -> "lastDetectedAt";
        };
        return Sort.by(Sort.Direction.valueOf(direction.name()), property);
    }
}
