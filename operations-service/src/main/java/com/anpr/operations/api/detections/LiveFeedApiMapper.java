package com.anpr.operations.api.detections;

import com.anpr.operations.api.generated.model.DeviceLiveState;
import com.anpr.operations.api.generated.model.GeoPoint;
import com.anpr.operations.api.generated.model.LiveFeedResponse;
import com.anpr.operations.api.generated.model.TrackPoint;
import com.anpr.operations.internal.livefeed.model.DeviceLive;
import com.anpr.operations.internal.livefeed.model.LiveFeed;
import com.anpr.operations.internal.locations.repository.LocationPoint;
import org.mapstruct.Mapper;
import org.mapstruct.Mapping;
import org.mapstruct.ReportingPolicy;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;

/** Detections go through DetectionApiMapper, so the live feed carries the same photo URL and alert as View 1. */
@Mapper(componentModel = "spring", uses = DetectionApiMapper.class, unmappedTargetPolicy = ReportingPolicy.ERROR)
public interface LiveFeedApiMapper {

    LiveFeedResponse toResponse(LiveFeed feed);

    @Mapping(target = "lastSeenAt", source = "lastLocation.recordedAt")
    @Mapping(target = "lastPosition", source = "lastLocation")
    DeviceLiveState toDeviceState(DeviceLive device);

    @Mapping(target = "position", source = ".")
    TrackPoint toTrackPoint(LocationPoint location);

    default GeoPoint toGeoPoint(LocationPoint location) {
        return location == null ? null : new GeoPoint(location.getLat(), location.getLon());
    }

    /** The contract carries times as UTC date-time. */
    default OffsetDateTime toUtc(Instant instant) {
        return instant == null ? null : instant.atOffset(ZoneOffset.UTC);
    }
}
