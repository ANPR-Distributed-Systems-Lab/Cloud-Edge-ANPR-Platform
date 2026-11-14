package com.anpr.devicemanagement.api.models;

import com.anpr.devicemanagement.api.common.TimeMapping;
import com.anpr.devicemanagement.api.generated.model.DeviceModelsResponse;
import com.anpr.devicemanagement.internal.models.DeviceModels;
import org.mapstruct.Mapper;
import org.mapstruct.ReportingPolicy;

@Mapper(componentModel = "spring", uses = TimeMapping.class, unmappedTargetPolicy = ReportingPolicy.ERROR)
public interface ModelsApiMapper {

    DeviceModelsResponse toResponse(DeviceModels models);
}
