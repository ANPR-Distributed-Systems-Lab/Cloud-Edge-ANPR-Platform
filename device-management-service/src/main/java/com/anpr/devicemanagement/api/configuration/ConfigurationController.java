package com.anpr.devicemanagement.api.configuration;

import com.anpr.devicemanagement.api.generated.ConfigurationApi;
import com.anpr.devicemanagement.api.generated.model.DeviceConfigurationResponse;
import com.anpr.devicemanagement.api.generated.model.UpdateDeviceConfigurationRequest;
import com.anpr.devicemanagement.internal.configuration.ConfigurationService;
import com.anpr.devicemanagement.internal.configuration.DeviceConfiguration;
import com.anpr.devicemanagement.shared.security.CurrentCaller;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class ConfigurationController implements ConfigurationApi {
    private final ConfigurationService configurationService;
    private final ConfigurationApiMapper mapper;
    private final CurrentCaller currentCaller;

    @Override
    public ResponseEntity<DeviceConfigurationResponse> getDeviceConfiguration(String ifNoneMatch) {
        DeviceConfiguration configuration = configurationService.get(currentCaller.get());
        String etag = ConfigurationETag.of(configuration.getVersion());
        if (ConfigurationETag.matches(ifNoneMatch, etag)) {
            return ResponseEntity.status(HttpStatus.NOT_MODIFIED).eTag(etag).build();
        }
        return ResponseEntity.ok().eTag(etag).body(mapper.toResponse(configuration));
    }

    @Override
    public ResponseEntity<DeviceConfigurationResponse> updateDeviceConfiguration(UpdateDeviceConfigurationRequest request) {
        DeviceConfiguration configuration = configurationService.update(
                currentCaller.get(), request.getVersion(), mapper.toSettings(request));
        return ResponseEntity.ok()
                .eTag(ConfigurationETag.of(configuration.getVersion()))
                .body(mapper.toResponse(configuration));
    }
}
