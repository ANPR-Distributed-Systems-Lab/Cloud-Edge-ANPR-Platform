package com.anpr.devicemanagement.api.models;

import com.anpr.devicemanagement.api.generated.ModelsApi;
import com.anpr.devicemanagement.api.generated.model.DeviceModelsResponse;
import com.anpr.devicemanagement.internal.models.ModelDownloadService;
import com.anpr.devicemanagement.shared.security.CurrentCaller;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class ModelsController implements ModelsApi {
    private final ModelDownloadService modelDownloadService;
    private final ModelsApiMapper mapper;
    private final CurrentCaller currentCaller;

    @Override
    public ResponseEntity<DeviceModelsResponse> getDeviceModels() {
        return ResponseEntity.ok(mapper.toResponse(modelDownloadService.downloads(currentCaller.get())));
    }
}
