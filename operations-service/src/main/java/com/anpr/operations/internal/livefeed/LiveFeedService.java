package com.anpr.operations.internal.livefeed;

import com.anpr.operations.internal.alerts.AlertService;
import com.anpr.operations.internal.detections.model.Detection;
import com.anpr.operations.internal.detections.model.DetectionWithAlert;
import com.anpr.operations.internal.detections.repository.DetectionRepository;
import com.anpr.operations.internal.devices.repository.DeviceRepository;
import com.anpr.operations.internal.livefeed.model.DeviceLive;
import com.anpr.operations.internal.livefeed.model.LiveFeed;
import com.anpr.operations.internal.locations.model.DeviceLocation;
import com.anpr.operations.internal.locations.repository.DeviceLocationRepository;
import com.anpr.operations.shared.security.CurrentAccount;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Limit;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.stream.Collectors;

/** View 3: the detections stored since the cursor of the client, and where the device of the account is. */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class LiveFeedService {
    /** Contract: at most 50 detections per response. */
    private static final int PAGE_SIZE = 50;
    /**
     * Contract: only detections stored at least 2 s ago. Two batches stored at the same time can commit in a different
     * order than they started; the delay lets the slower one commit before the cursor passes it.
     */
    private static final Duration SETTLE_TIME = Duration.ofSeconds(2);

    private final DetectionRepository detectionRepository;
    private final DeviceRepository deviceRepository;
    private final DeviceLocationRepository locationRepository;
    private final AlertService alertService;
    private final CurrentAccount currentAccount;
    private final Clock clock;

    public LiveFeed poll(String cursor, int windowMinutes) {
        UUID accountId = currentAccount.id();
        OffsetDateTime now = OffsetDateTime.now(clock);
        OffsetDateTime storedUntil = now.minus(SETTLE_TIME);

        Batch batch = cursor == null
                ? latest(accountId, storedUntil)
                : after(accountId, LiveFeedCursor.decode(cursor), storedUntil);

        return new LiveFeed(withAlerts(accountId, batch.detections()), batch.next().encode(), batch.hasMore(),
                devices(accountId, now.minusMinutes(windowMinutes)));
    }

    /** First poll: the newest detections, in the order they were stored. Older ones are history (View 1). */
    private Batch latest(UUID accountId, OffsetDateTime storedUntil) {
        List<Detection> newestFirst = detectionRepository.findLatestStored(accountId, storedUntil, Limit.of(PAGE_SIZE));
        if (newestFirst.isEmpty()) {
            return new Batch(List.of(), false, LiveFeedCursor.startingAt(storedUntil));
        }
        return new Batch(newestFirst.reversed(), false, LiveFeedCursor.after(newestFirst.getFirst()));
    }

    /** One row more than a page tells whether more are waiting, without a separate count. */
    private Batch after(UUID accountId, LiveFeedCursor cursor, OffsetDateTime storedUntil) {
        List<Detection> found = detectionRepository.findStoredAfter(accountId, cursor.storedAt(), cursor.detectionId(),
                storedUntil, Limit.of(PAGE_SIZE + 1));
        boolean hasMore = found.size() > PAGE_SIZE;
        List<Detection> page = hasMore ? found.subList(0, PAGE_SIZE) : found;
        LiveFeedCursor next = page.isEmpty() ? cursor : LiveFeedCursor.after(page.getLast());
        return new Batch(page, hasMore, next);
    }

    private List<DetectionWithAlert> withAlerts(UUID accountId, List<Detection> detections) {
        Map<String, UUID> alertIds = alertService.alertIdsByPlate(accountId,
                detections.stream().map(Detection::getPlate).collect(Collectors.toSet()));
        return detections.stream()
                .map(detection -> new DetectionWithAlert(detection, alertIds.get(detection.getPlate())))
                .toList();
    }

    /** The device currently paired with the account; none when it is unpaired or has sent no position yet. */
    private List<DeviceLive> devices(UUID accountId, OffsetDateTime since) {
        return deviceRepository.findPairedDeviceId(accountId)
                .flatMap(deviceId -> liveState(accountId, deviceId, since))
                .stream()
                .toList();
    }

    /** The last point of the route is the latest position; only a device silent for the whole window needs a lookup. */
    private Optional<DeviceLive> liveState(UUID accountId, UUID deviceId, OffsetDateTime since) {
        List<DeviceLocation> track = locationRepository.findTrack(accountId, deviceId, since);
        Optional<DeviceLocation> last = track.isEmpty()
                ? locationRepository.findFirstByAccountIdAndDeviceIdOrderByRecordedAtDesc(accountId, deviceId)
                : Optional.of(track.getLast());
        return last.map(location -> new DeviceLive(deviceId, location, track));
    }

    private record Batch(List<Detection> detections, boolean hasMore, LiveFeedCursor next) {
    }
}
