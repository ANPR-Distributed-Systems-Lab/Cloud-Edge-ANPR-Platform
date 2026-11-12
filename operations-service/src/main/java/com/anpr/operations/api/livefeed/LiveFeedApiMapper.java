package com.anpr.operations.api.livefeed;

import com.anpr.operations.api.generated.model.DeviceLiveState;
import com.anpr.operations.api.generated.model.LiveFeedResponse;
import com.anpr.operations.api.generated.model.TrackPoint;
import com.anpr.operations.api.search.DetectionApiMapper;
import com.anpr.operations.internal.livefeed.model.DeviceLive;
import com.anpr.operations.internal.livefeed.model.LiveFeed;
import com.anpr.operations.internal.locations.model.DeviceLocation;
import org.mapstruct.Mapper;
import org.mapstruct.Mapping;
import org.mapstruct.ReportingPolicy;

/** Detections go through DetectionApiMapper, so the live feed carries the same photo URL and alert as View 1. */
@Mapper(componentModel = "spring", uses = DetectionApiMapper.class, unmappedTargetPolicy = ReportingPolicy.ERROR)
public interface LiveFeedApiMapper {

    LiveFeedResponse toResponse(LiveFeed feed);

    @Mapping(target = "lastSeenAt", source = "lastLocation.recordedAt")
    @Mapping(target = "lastPosition", source = "lastLocation.position")
    DeviceLiveState toDeviceState(DeviceLive device);

    TrackPoint toTrackPoint(DeviceLocation location);
}
