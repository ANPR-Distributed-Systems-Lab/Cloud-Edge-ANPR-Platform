package com.anpr.operations.api.search;

import com.anpr.operations.api.generated.AnprSearchApi;
import com.anpr.operations.api.generated.model.DetectionPage;
import com.anpr.operations.api.generated.model.DetectionSortField;
import com.anpr.operations.api.generated.model.PlateSuggestionList;
import com.anpr.operations.api.generated.model.SortDirection;
import com.anpr.operations.internal.detections.DetectionSearchService;
import com.anpr.operations.internal.detections.model.DetectionFilter;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

import java.time.OffsetDateTime;

@RestController
@RequiredArgsConstructor
public class DetectionSearchController implements AnprSearchApi {
    private final DetectionSearchService searchService;
    private final DetectionApiMapper mapper;

    @Override
    public ResponseEntity<DetectionPage> searchDetections(String plate, OffsetDateTime from, OffsetDateTime to,
                                                          Integer page, Integer size, DetectionSortField sort,
                                                          SortDirection direction) {
        PageRequest pageable = PageRequest.of(page, size, toSort(sort, direction));
        return ResponseEntity.ok(mapper.toPage(searchService.search(new DetectionFilter(plate, from, to), pageable)));
    }

    @Override
    public ResponseEntity<PlateSuggestionList> suggestPlates(String q, Integer limit) {
        return ResponseEntity.ok(mapper.toSuggestions(searchService.suggestPlates(q, limit)));
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