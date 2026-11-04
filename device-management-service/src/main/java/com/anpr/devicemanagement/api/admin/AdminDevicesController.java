package com.anpr.devicemanagement.api.admin;

import com.anpr.devicemanagement.api.generated.AdminApi;
import com.anpr.devicemanagement.api.generated.model.CreateDeviceRequest;
import com.anpr.devicemanagement.api.generated.model.CreatedDeviceResponse;
import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.provisioning.DeviceProvisioningService;
import com.anpr.devicemanagement.shared.security.CurrentCaller;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

import java.util.UUID;

@RestController
@RequiredArgsConstructor
public class AdminDevicesController implements AdminApi {
    private final DeviceProvisioningService provisioningService;
    private final AdminApiMapper mapper;
    private final CurrentCaller currentCaller;

    @Override
    public ResponseEntity<CreatedDeviceResponse> createDevice(CreateDeviceRequest request) {
        Device device = provisioningService.create(currentCaller.get(), mapper.toNewDevice(request));
        return ResponseEntity.status(HttpStatus.CREATED).body(mapper.toResponse(device));
    }

    @Override
    public ResponseEntity<Void> deleteDevice(UUID deviceId) {
        provisioningService.delete(currentCaller.get(), deviceId);
        return ResponseEntity.noContent().build();
    }
}
