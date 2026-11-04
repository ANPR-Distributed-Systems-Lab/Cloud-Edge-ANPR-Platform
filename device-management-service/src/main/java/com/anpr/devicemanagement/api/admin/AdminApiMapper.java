package com.anpr.devicemanagement.api.admin;

import com.anpr.devicemanagement.api.common.TimeMapping;
import com.anpr.devicemanagement.api.generated.model.CreateDeviceRequest;
import com.anpr.devicemanagement.api.generated.model.CreatedDeviceResponse;
import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.provisioning.NewDevice;
import org.mapstruct.Mapper;
import org.mapstruct.ReportingPolicy;

@Mapper(componentModel = "spring", uses = TimeMapping.class, unmappedTargetPolicy = ReportingPolicy.ERROR)
public interface AdminApiMapper {

    NewDevice toNewDevice(CreateDeviceRequest request);

    CreatedDeviceResponse toResponse(Device device);
}
