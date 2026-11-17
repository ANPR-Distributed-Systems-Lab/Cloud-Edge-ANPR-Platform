package com.anpr.operations.internal.radial;

import com.anpr.operations.internal.detections.DetectionService;
import com.anpr.operations.internal.detections.model.DetectionWithAlert;
import com.anpr.operations.internal.locations.DeviceLocationService;
import com.anpr.operations.internal.locations.repository.DevicePoint;
import com.anpr.operations.internal.radial.model.DeviceRoute;
import com.anpr.operations.internal.radial.model.RadialAnalysis;
import com.anpr.operations.internal.radial.model.RadialQuery;
import com.anpr.operations.shared.error.BadRequestException;
import com.anpr.operations.shared.error.ErrorCodes;
import com.anpr.operations.shared.security.CurrentAccount;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

/** View 2: who was detected inside a circle in a time range, and where the devices of the account drove meanwhile. */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class RadialAnalysisService {
    /** Contract (D10): at most 5000 detections, and 5000 route points per device. */
    static final int MAX_ITEMS = 5000;
    /** Contract (D10): the time range spans at most 7 days. */
    static final Duration MAX_RANGE = Duration.ofDays(7);

    private final DetectionService detectionService;
    private final DeviceLocationService locationService;
    private final CurrentAccount currentAccount;

    public RadialAnalysis analyze(RadialQuery query) {
        if (query.period().isLongerThan(MAX_RANGE)) {
            throw new BadRequestException(ErrorCodes.VALIDATION_FAILED, "The time range may span at most 7 days");
        }
        UUID accountId = currentAccount.id();

        // One row more than the limit tells whether anything was cut off, without a separate count.
        List<DetectionWithAlert> newestFirst = detectionService.withinRadius(accountId, query.lat(), query.lon(),
                query.radiusMeters(), query.period(), MAX_ITEMS + 1);
        boolean truncated = newestFirst.size() > MAX_ITEMS;
        List<DetectionWithAlert> detections =
                newestFirst.subList(0, Math.min(newestFirst.size(), MAX_ITEMS)).reversed();

        return new RadialAnalysis(query.lat(), query.lon(), query.radiusMeters(), detections, truncated,
                routes(accountId, query));
    }

    /**
     * Routes of every device that recorded positions in the account in the range, not only the paired one: View 2 is
     * history, and the route of a replaced device must stay visible.
     */
    private List<DeviceRoute> routes(UUID accountId, RadialQuery query) {
        Map<UUID, List<DevicePoint>> byDevice = locationService
                .tracks(accountId, query.period(), query.trackIntervalSeconds(), MAX_ITEMS + 1).stream()
                .collect(Collectors.groupingBy(DevicePoint::getDeviceId, LinkedHashMap::new, Collectors.toList()));
        return byDevice.entrySet().stream().map(e -> route(e.getKey(), e.getValue())).toList();
    }

    /** Points come oldest first; one too many means the oldest is dropped, as the contract keeps the most recent. */
    private static DeviceRoute route(UUID deviceId, List<DevicePoint> points) {
        boolean truncated = points.size() > MAX_ITEMS;
        return new DeviceRoute(deviceId, List.copyOf(truncated ? points.subList(1, points.size()) : points),
                truncated);
    }
}
