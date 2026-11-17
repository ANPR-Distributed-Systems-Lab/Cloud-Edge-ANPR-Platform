package com.anpr.operations.api.detections;

import com.anpr.operations.api.generated.model.DeviceTrack;
import com.anpr.operations.api.generated.model.GeoPoint;
import com.anpr.operations.api.generated.model.RadialAnalysisResponse;
import com.anpr.operations.internal.radial.model.DeviceRoute;
import com.anpr.operations.internal.radial.model.RadialAnalysis;
import org.mapstruct.Mapper;
import org.mapstruct.Mapping;
import org.mapstruct.ReportingPolicy;

/**
 * Detections go through DetectionApiMapper and route points through LiveFeedApiMapper, so View 2 carries the same
 * photo URL, alert and point shape as Views 1 and 3.
 */
@Mapper(componentModel = "spring", uses = {DetectionApiMapper.class, LiveFeedApiMapper.class},
        imports = GeoPoint.class, unmappedTargetPolicy = ReportingPolicy.ERROR)
public interface RadialAnalysisApiMapper {

    @Mapping(target = "center", expression = "java(new GeoPoint(analysis.centerLat(), analysis.centerLon()))")
    @Mapping(target = "tracks", source = "routes")
    RadialAnalysisResponse toResponse(RadialAnalysis analysis);

    DeviceTrack toTrack(DeviceRoute route);
}
