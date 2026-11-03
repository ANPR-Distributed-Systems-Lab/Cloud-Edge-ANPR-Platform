package com.anpr.devicemanagement.api.configuration;

import com.anpr.devicemanagement.api.common.TimeMapping;
import com.anpr.devicemanagement.api.generated.model.DeviceConfigurationResponse;
import com.anpr.devicemanagement.api.generated.model.UpdateDeviceConfigurationRequest;
import com.anpr.devicemanagement.internal.configuration.DeviceConfiguration;
import com.anpr.devicemanagement.internal.configuration.DeviceSettings;
import org.mapstruct.Mapper;
import org.mapstruct.Mapping;
import org.mapstruct.ReportingPolicy;

/** The contract shows the settings at the top level of the configuration, next to its version. */
@Mapper(componentModel = "spring", uses = TimeMapping.class, unmappedTargetPolicy = ReportingPolicy.ERROR)
public interface ConfigurationApiMapper {

    @Mapping(target = ".", source = "settings")
    DeviceConfigurationResponse toResponse(DeviceConfiguration configuration);

    DeviceSettings toSettings(UpdateDeviceConfigurationRequest request);
}
