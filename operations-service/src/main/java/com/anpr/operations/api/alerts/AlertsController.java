package com.anpr.operations.api.alerts;

import com.anpr.operations.api.generated.AlertsApi;
import com.anpr.operations.api.generated.model.AlertPage;
import com.anpr.operations.api.generated.model.AlertResponse;
import com.anpr.operations.api.generated.model.AlertSortField;
import com.anpr.operations.api.generated.model.CreateAlertRequest;
import com.anpr.operations.api.generated.model.SortDirection;
import com.anpr.operations.api.generated.model.UpdateAlertRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

import java.time.OffsetDateTime;
import java.util.UUID;

@RestController
@RequiredArgsConstructor
public class AlertsController implements AlertsApi {
    private final AlertsFacade facade;

    @Override
    public ResponseEntity<AlertResponse> createAlert(CreateAlertRequest request) {
        return facade.create(request.getPlate(), request.getAlertText());
    }

    @Override
    public ResponseEntity<AlertResponse> getAlert(UUID alertId) {
        return facade.get(alertId);
    }

    @Override
    public ResponseEntity<AlertPage> listAlerts(Integer page, Integer size, AlertSortField sort, SortDirection direction,
                                                String plate, OffsetDateTime from, OffsetDateTime to,
                                                String ifNoneMatch) {
        return facade.list(page, size, sort, direction, plate, from, to, ifNoneMatch);
    }

    @Override
    public ResponseEntity<AlertResponse> updateAlert(UUID alertId, UpdateAlertRequest request) {
        return facade.update(alertId, request.getAlertText(), request.getVersion());
    }

    @Override
    public ResponseEntity<Void> deleteAlert(UUID alertId) {
        return facade.delete(alertId);
    }
}
