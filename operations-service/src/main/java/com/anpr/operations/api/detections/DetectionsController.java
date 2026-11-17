package com.anpr.operations.api.detections;

import com.anpr.operations.api.generated.DetectionsApi;
import com.anpr.operations.api.generated.model.DetectionPage;
import com.anpr.operations.api.generated.model.DetectionResponse;
import com.anpr.operations.api.generated.model.DetectionSortField;
import com.anpr.operations.api.generated.model.LiveFeedResponse;
import com.anpr.operations.api.generated.model.PlateSuggestionList;
import com.anpr.operations.api.generated.model.RadialAnalysisResponse;
import com.anpr.operations.api.generated.model.SortDirection;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

import java.time.OffsetDateTime;
import java.util.UUID;

/** Every endpoint under /api/v1/detections (tag "detections" of the contract). */
@RestController
@RequiredArgsConstructor
public class DetectionsController implements DetectionsApi {
    private final DetectionsFacade facade;

    /** View 1. */
    @Override
    public ResponseEntity<DetectionPage> searchDetections(String plate, OffsetDateTime from, OffsetDateTime to,
                                                          Integer page, Integer size, DetectionSortField sort,
                                                          SortDirection direction) {
        return facade.search(plate, from, to, page, size, sort, direction);
    }

    /** View 1. */
    @Override
    public ResponseEntity<PlateSuggestionList> suggestPlates(String q, Integer limit) {
        return facade.suggestPlates(q, limit);
    }

    /** View 2. */
    @Override
    public ResponseEntity<RadialAnalysisResponse> analyzeRadius(Double lat, Double lon, Integer radiusMeters,
                                                                OffsetDateTime from, OffsetDateTime to,
                                                                Integer trackIntervalSeconds) {
        return facade.radialAnalysis(lat, lon, radiusMeters, from, to, trackIntervalSeconds);
    }

    /** View 3. */
    @Override
    public ResponseEntity<LiveFeedResponse> getLiveFeed(String cursor, Integer windowMinutes) {
        return facade.liveFeed(cursor, windowMinutes);
    }

    /** D18. */
    @Override
    public ResponseEntity<DetectionResponse> getDetection(UUID detectionId) {
        return facade.get(detectionId);
    }
}
