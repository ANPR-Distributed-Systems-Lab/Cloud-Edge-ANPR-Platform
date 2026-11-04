package com.anpr.devicemanagement.api.metrics;

import com.anpr.devicemanagement.api.common.TimeMapping;
import com.anpr.devicemanagement.api.generated.model.DeviceMetric;
import com.anpr.devicemanagement.api.generated.model.DeviceMetricsResponse;
import com.anpr.devicemanagement.api.generated.model.GpsState;
import com.anpr.devicemanagement.internal.metrics.Measurement;
import com.anpr.devicemanagement.internal.metrics.MetricsService.DeviceMeasurements;
import org.mapstruct.InheritInverseConfiguration;
import org.mapstruct.Mapper;
import org.mapstruct.Mapping;
import org.mapstruct.ReportingPolicy;
import org.mapstruct.ValueMapping;

import java.util.List;

@Mapper(componentModel = "spring", uses = TimeMapping.class, unmappedTargetPolicy = ReportingPolicy.ERROR)
public interface MetricsApiMapper {

    /** The device and the expiry are assigned by the service. */
    @Mapping(target = "deviceId", ignore = true)
    @Mapping(target = "expiresAt", ignore = true)
    Measurement toMeasurement(DeviceMetric metric);

    List<Measurement> toMeasurements(List<DeviceMetric> metrics);

    DeviceMetric toMetric(Measurement measurement);

    @Mapping(target = "metrics", source = "measurements")
    DeviceMetricsResponse toResponse(DeviceMeasurements measurements);

    /** The generator names the constants FIX_2_D and FIX_3_D; their JSON values are FIX_2D and FIX_3D. */
    @ValueMapping(target = "FIX_2D", source = "FIX_2_D")
    @ValueMapping(target = "FIX_3D", source = "FIX_3_D")
    Measurement.GpsFix toGpsFix(GpsState.FixEnum fix);

    @InheritInverseConfiguration
    GpsState.FixEnum toFixEnum(Measurement.GpsFix fix);
}
