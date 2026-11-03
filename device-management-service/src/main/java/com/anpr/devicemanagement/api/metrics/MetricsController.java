package com.anpr.devicemanagement.api.metrics;

import com.anpr.devicemanagement.api.common.TimeMapping;
import com.anpr.devicemanagement.api.generated.MetricsApi;
import com.anpr.devicemanagement.api.generated.model.DeviceMetricsResponse;
import com.anpr.devicemanagement.api.generated.model.ReportMetricsRequest;
import com.anpr.devicemanagement.internal.metrics.MetricsService;
import com.anpr.devicemanagement.shared.security.CurrentCaller;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

import java.time.OffsetDateTime;

@RestController
@RequiredArgsConstructor
public class MetricsController implements MetricsApi {
    private final MetricsService metricsService;
    private final MetricsApiMapper mapper;
    private final TimeMapping time;
    private final CurrentCaller currentCaller;

    @Override
    public ResponseEntity<Void> reportDeviceMetrics(ReportMetricsRequest request) {
        metricsService.report(currentCaller.get(), mapper.toMeasurements(request.getMetrics()));
        return ResponseEntity.noContent().build();
    }

    @Override
    public ResponseEntity<DeviceMetricsResponse> listDeviceMetrics(Integer limit, OffsetDateTime before) {
        return ResponseEntity.ok(mapper.toResponse(
                metricsService.latest(currentCaller.get(), limit, time.toInstant(before))));
    }
}
