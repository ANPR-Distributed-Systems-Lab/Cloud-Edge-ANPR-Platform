package com.anpr.devicemanagement.api.device;

import com.anpr.devicemanagement.api.generated.DeviceApi;
import com.anpr.devicemanagement.api.generated.model.DeviceResponse;
import com.anpr.devicemanagement.internal.overview.DeviceOverviewService;
import com.anpr.devicemanagement.shared.security.CurrentCaller;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class DeviceController implements DeviceApi {
    private final DeviceOverviewService overviewService;
    private final DeviceApiMapper mapper;
    private final CurrentCaller currentCaller;

    @Override
    public ResponseEntity<DeviceResponse> getDevice() {
        return ResponseEntity.ok(mapper.toResponse(overviewService.overviewOf(currentCaller.get())));
    }
}
