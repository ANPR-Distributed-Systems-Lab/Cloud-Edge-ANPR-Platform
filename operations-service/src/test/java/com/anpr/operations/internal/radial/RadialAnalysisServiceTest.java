package com.anpr.operations.internal.radial;

import com.anpr.operations.internal.detections.DetectionService;
import com.anpr.operations.internal.detections.model.Detection;
import com.anpr.operations.internal.detections.model.DetectionWithAlert;
import com.anpr.operations.internal.locations.DeviceLocationService;
import com.anpr.operations.internal.locations.repository.DevicePoint;
import com.anpr.operations.internal.radial.model.DeviceRoute;
import com.anpr.operations.internal.radial.model.RadialAnalysis;
import com.anpr.operations.internal.radial.model.RadialQuery;
import com.anpr.operations.shared.error.BadRequestException;
import com.anpr.operations.shared.error.ErrorCodes;
import com.anpr.operations.shared.geo.Wgs84;
import com.anpr.operations.shared.security.CurrentAccount;
import com.anpr.operations.shared.time.TimeRange;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
import java.util.stream.IntStream;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyDouble;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class RadialAnalysisServiceTest {
    private static final UUID ACCOUNT = UUID.fromString("11111111-1111-1111-1111-111111111111");
    private static final UUID DEVICE = UUID.fromString("22222222-2222-2222-2222-222222222222");
    private static final UUID REPLACED_DEVICE = UUID.fromString("33333333-3333-3333-3333-333333333333");
    private static final OffsetDateTime FROM = OffsetDateTime.of(2026, 10, 30, 0, 0, 0, 0, ZoneOffset.UTC);
    private static final int LIMIT = RadialAnalysisService.MAX_ITEMS;

    @Mock private DetectionService detectionService;
    @Mock private DeviceLocationService locationService;
    @Mock private CurrentAccount currentAccount;
    @InjectMocks private RadialAnalysisService service;

    @Test
    void aRangeLongerThanSevenDaysIsRejectedBeforeAnyQuery() {
        assertThatThrownBy(() -> service.analyze(query(FROM.plusDays(7).plusSeconds(1))))
                .isInstanceOfSatisfying(BadRequestException.class,
                        e -> assertThat(e.getCode()).isEqualTo(ErrorCodes.VALIDATION_FAILED));
        verifyNoInteractions(detectionService, locationService);
    }

    @Test
    void bothQueriesUseTheCallerAccountAndAskForOneRowMoreThanTheLimit() {
        when(currentAccount.id()).thenReturn(ACCOUNT);
        RadialQuery query = query(FROM.plusDays(7));

        service.analyze(query);

        verify(detectionService).withinRadius(ACCOUNT, query.lat(), query.lon(), query.radiusMeters(),
                query.period(), LIMIT + 1);
        verify(locationService).tracks(ACCOUNT, query.period(), query.trackIntervalSeconds(), LIMIT + 1);
    }

    @Test
    void detectionsAreReturnedOldestFirst() {
        givenDetectionsNewestFirst(3);

        RadialAnalysis analysis = analyze();

        assertThat(analysis.detections()).extracting(d -> d.detection().getDetectedAt())
                .containsExactly(FROM.plusSeconds(1), FROM.plusSeconds(2), FROM.plusSeconds(3));
        assertThat(analysis.truncated()).isFalse();
    }

    @Test
    void exactlyTheLimitOfDetectionsIsNotTruncated() {
        givenDetectionsNewestFirst(LIMIT);

        RadialAnalysis analysis = analyze();

        assertThat(analysis.detections()).hasSize(LIMIT);
        assertThat(analysis.truncated()).isFalse();
    }

    @Test
    void aboveTheLimitTheNewestDetectionsAreKept() {
        givenDetectionsNewestFirst(LIMIT + 1);

        RadialAnalysis analysis = analyze();

        assertThat(analysis.detections()).hasSize(LIMIT);
        assertThat(analysis.detections().getFirst().detection().getDetectedAt()).isEqualTo(FROM.plusSeconds(2));
        assertThat(analysis.detections().getLast().detection().getDetectedAt()).isEqualTo(FROM.plusSeconds(LIMIT + 1));
        assertThat(analysis.truncated()).isTrue();
    }

    @Test
    void everyDeviceGetsItsOwnRouteInTheOrderOfTheQuery() {
        when(locationService.tracks(any(), any(), anyInt(), anyInt())).thenReturn(List.of(
                point(REPLACED_DEVICE, 1), point(REPLACED_DEVICE, 2), point(DEVICE, 3)));

        RadialAnalysis analysis = analyze();

        assertThat(analysis.routes()).extracting(DeviceRoute::deviceId).containsExactly(REPLACED_DEVICE, DEVICE);
        assertThat(analysis.routes().getFirst().points()).hasSize(2);
        assertThat(analysis.routes()).noneMatch(DeviceRoute::truncated);
    }

    @Test
    void aRouteAboveTheLimitDropsItsOldestPointAndOnlyThatRouteIsTruncated() {
        List<DevicePoint> full = IntStream.rangeClosed(1, LIMIT + 1).mapToObj(i -> point(DEVICE, i)).toList();
        when(locationService.tracks(any(), any(), anyInt(), anyInt()))
                .thenReturn(concat(List.of(point(REPLACED_DEVICE, 0)), full));

        RadialAnalysis analysis = analyze();

        DeviceRoute replaced = analysis.routes().get(0);
        DeviceRoute current = analysis.routes().get(1);
        assertThat(replaced.truncated()).isFalse();
        assertThat(current.truncated()).isTrue();
        assertThat(current.points()).hasSize(LIMIT);
        assertThat(current.points().getFirst().getRecordedAt()).isEqualTo(FROM.plusSeconds(2).toInstant());
    }

    private RadialAnalysis analyze() {
        when(currentAccount.id()).thenReturn(ACCOUNT);
        return service.analyze(query(FROM.plusDays(1)));
    }

    private static RadialQuery query(OffsetDateTime to) {
        return new RadialQuery(52.2297, 21.0122, 500, new TimeRange(FROM, to), 1);
    }

    /** As the repository returns them: newest first, detected at FROM + count seconds down to FROM + 1 second. */
    private void givenDetectionsNewestFirst(int count) {
        List<DetectionWithAlert> newestFirst = IntStream.iterate(count, i -> i >= 1, i -> i - 1)
                .mapToObj(i -> new DetectionWithAlert(Detection.create(UUID.randomUUID(), ACCOUNT, DEVICE, "WA12345",
                        FROM.plusSeconds(i), Wgs84.point(52.2297, 21.0122), 0.9, 0.8, "images/x.jpg"), null))
                .toList();
        when(detectionService.withinRadius(eq(ACCOUNT), anyDouble(), anyDouble(), anyInt(), any(), anyInt()))
                .thenReturn(newestFirst);
    }

    private static DevicePoint point(UUID deviceId, int second) {
        return new Point(deviceId, FROM.plusSeconds(second).toInstant());
    }

    private static List<DevicePoint> concat(List<DevicePoint> first, List<DevicePoint> second) {
        return Stream.concat(first.stream(), second.stream()).toList();
    }

    private record Point(UUID getDeviceId, Instant getRecordedAt) implements DevicePoint {
        @Override
        public double getLat() {
            return 52.2297;
        }

        @Override
        public double getLon() {
            return 21.0122;
        }
    }
}
