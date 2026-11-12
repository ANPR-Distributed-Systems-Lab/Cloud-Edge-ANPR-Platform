package com.anpr.operations.api.livefeed;

import com.anpr.operations.api.generated.LiveFeedApi;
import com.anpr.operations.api.generated.model.LiveFeedResponse;
import com.anpr.operations.internal.livefeed.LiveFeedService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
public class LiveFeedController implements LiveFeedApi {
    private final LiveFeedService liveFeedService;
    private final LiveFeedApiMapper mapper;

    @Override
    public ResponseEntity<LiveFeedResponse> getLiveFeed(String cursor, Integer windowMinutes) {
        return ResponseEntity.ok(mapper.toResponse(liveFeedService.poll(cursor, windowMinutes)));
    }
}
