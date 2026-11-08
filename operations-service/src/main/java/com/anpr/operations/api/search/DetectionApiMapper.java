package com.anpr.operations.api.search;

import com.anpr.operations.api.generated.model.DetectionPage;
import com.anpr.operations.api.generated.model.DetectionResponse;
import com.anpr.operations.api.generated.model.GeoPoint;
import com.anpr.operations.api.generated.model.PageMeta;
import com.anpr.operations.api.generated.model.PlateSuggestion;
import com.anpr.operations.api.generated.model.PlateSuggestionList;
import com.anpr.operations.internal.detections.model.Detection;
import com.anpr.operations.internal.detections.model.DetectionWithAlert;
import com.anpr.operations.internal.detections.repository.PlateSuggestionRow;
import org.locationtech.jts.geom.Point;
import org.mapstruct.Mapper;
import org.mapstruct.Mapping;
import org.mapstruct.ReportingPolicy;
import org.springframework.data.domain.Page;

import java.util.List;

@Mapper(componentModel = "spring", unmappedTargetPolicy = ReportingPolicy.ERROR)
public interface DetectionApiMapper {
    // Presigned photo URLs come in a separate change; the contract allows null.
    @Mapping(target = "imageUrl", ignore = true)
    @Mapping(target = "alertId", ignore = true)
    DetectionResponse toDetection(Detection detection);

    default DetectionResponse toResponse(DetectionWithAlert found) {
        return toDetection(found.detection()).alertId(found.alertId());
    }

    default DetectionPage toPage(Page<DetectionWithAlert> page){
        return new DetectionPage()
                .items(page.map(this::toResponse).getContent())
                .page(new PageMeta()
                        .page(page.getNumber())
                        .size(page.getSize())
                        .totalElements(page.getTotalElements())
                        .totalPages(page.getTotalPages()));
    }

    /** JTS keeps x = longitude and y = latitude. */
    default GeoPoint toGeoPoint(Point point) {
        return new GeoPoint(point.getY(), point.getX());
    }

    PlateSuggestion toSuggestion(PlateSuggestionRow row);

    default PlateSuggestionList toSuggestions(List<PlateSuggestionRow> rows){
        return new PlateSuggestionList().items(rows.stream().map(this::toSuggestion).toList());
    }
}
