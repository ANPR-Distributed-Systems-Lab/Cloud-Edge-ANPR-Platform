package com.anpr.devicemanagement.api.device;

import com.anpr.devicemanagement.api.common.TimeMapping;
import com.anpr.devicemanagement.api.generated.model.DeviceResponse;
import com.anpr.devicemanagement.internal.overview.DeviceOverview;
import org.mapstruct.Mapper;
import org.mapstruct.Mapping;
import org.mapstruct.ReportingPolicy;

@Mapper(componentModel = "spring", uses = TimeMapping.class, unmappedTargetPolicy = ReportingPolicy.ERROR)
public interface DeviceApiMapper {

    @Mapping(target = "deviceId", source = "device.deviceId")
    @Mapping(target = "username", source = "device.username")
    @Mapping(target = "createdAt", source = "device.createdAt")
    DeviceResponse toResponse(DeviceOverview overview);
}
