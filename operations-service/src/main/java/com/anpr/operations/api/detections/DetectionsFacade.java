package com.anpr.operations.api.detections;

import com.anpr.operations.api.generated.model.DetectionPage;
import com.anpr.operations.api.generated.model.DetectionResponse;
import com.anpr.operations.api.generated.model.DetectionSortField;
import com.anpr.operations.api.generated.model.LiveFeedResponse;
import com.anpr.operations.api.generated.model.PlateSuggestionList;
import com.anpr.operations.api.generated.model.RadialAnalysisResponse;
import com.anpr.operations.api.generated.model.SortDirection;
import com.anpr.operations.internal.detections.DetectionService;
import com.anpr.operations.internal.detections.model.DetectionFilter;
import com.anpr.operations.internal.livefeed.LiveFeedService;
import com.anpr.operations.internal.radial.RadialAnalysisService;
import com.anpr.operations.internal.radial.model.RadialQuery;
import com.anpr.operations.shared.time.TimeRange;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Component;

import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * Every endpoint under /api/v1/detections (Views 1, 2 and 3, D18) between its controller and the services: builds
 * filters and sorting, maps the result and returns the HTTP response.
 */
@Component
@RequiredArgsConstructor
public class DetectionsFacade {
    private final DetectionService detectionService;
    private final LiveFeedService liveFeedService;
    private final RadialAnalysisService radialAnalysisService;
    private final DetectionApiMapper detectionMapper;
    private final LiveFeedApiMapper liveFeedMapper;
    private final RadialAnalysisApiMapper radialMapper;

    /** D18. */
    public ResponseEntity<DetectionResponse> get(UUID detectionId) {
        return ResponseEntity.ok(detectionMapper.toResponseWithAlert(detectionService.get(detectionId)));
    }

    /** View 1. */
    public ResponseEntity<DetectionPage> search(String plate, OffsetDateTime from, OffsetDateTime to, int page,
                                                int size, DetectionSortField sort, SortDirection direction) {
        PageRequest pageable = PageRequest.of(page, size, toSort(sort, direction));
        return ResponseEntity.ok(detectionMapper.toPage(
                detectionService.search(new DetectionFilter(plate, new TimeRange(from, to)), pageable)));
    }

    /** View 1. */
    public ResponseEntity<PlateSuggestionList> suggestPlates(String prefix, int limit) {
        return ResponseEntity.ok(detectionMapper.toSuggestions(detectionService.suggestPlates(prefix, limit)));
    }

    /** View 2. */
    public ResponseEntity<RadialAnalysisResponse> radialAnalysis(double lat, double lon, int radiusMeters,
                                                                 OffsetDateTime from, OffsetDateTime to,
                                                                 int trackIntervalSeconds) {
        RadialQuery query = new RadialQuery(lat, lon, radiusMeters, new TimeRange(from, to), trackIntervalSeconds);
        return ResponseEntity.ok(radialMapper.toResponse(radialAnalysisService.analyze(query)));
    }

    /** View 3. */
    public ResponseEntity<LiveFeedResponse> liveFeed(String cursor, int windowMinutes) {
        return ResponseEntity.ok(liveFeedMapper.toResponse(liveFeedService.poll(cursor, windowMinutes)));
    }

    private static Sort toSort(DetectionSortField field, SortDirection direction) {
        String property = switch (field) {
            case DETECTED_AT -> "detectedAt";
            case PLATE -> "plate";
        };
        // The id breaks ties, so a row never moves between pages when many share a plate or a time.
        return Sort.by(Sort.Direction.valueOf(direction.name()), property).and(Sort.by("detectionId"));
    }
}
