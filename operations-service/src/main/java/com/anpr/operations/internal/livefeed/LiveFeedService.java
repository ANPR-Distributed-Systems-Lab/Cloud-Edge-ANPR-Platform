package com.anpr.operations.internal.livefeed;

import com.anpr.operations.internal.detections.DetectionService;
import com.anpr.operations.internal.detections.model.DetectionWithAlert;
import com.anpr.operations.internal.devices.DevicePairingService;
import com.anpr.operations.internal.livefeed.model.DeviceLive;
import com.anpr.operations.internal.livefeed.model.LiveFeed;
import com.anpr.operations.internal.locations.DeviceLocationService;
import com.anpr.operations.internal.locations.model.DeviceLocation;
import com.anpr.operations.shared.security.CurrentAccount;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

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

    private final DetectionService detectionService;
    private final DevicePairingService pairingService;
    private final DeviceLocationService locationService;
    private final CurrentAccount currentAccount;
    private final Clock clock;

    public LiveFeed poll(String cursor, int windowMinutes) {
        UUID accountId = currentAccount.id();
        OffsetDateTime now = OffsetDateTime.now(clock);
        OffsetDateTime storedUntil = now.minus(SETTLE_TIME);

        Batch batch = cursor == null
                ? latest(accountId, storedUntil)
                : after(accountId, LiveFeedCursor.decode(cursor), storedUntil);

        return new LiveFeed(batch.detections(), batch.next().encode(), batch.hasMore(),
                devices(accountId, now.minusMinutes(windowMinutes)));
    }

    /** First poll: the newest detections, in the order they were stored. Older ones are history (View 1). */
    private Batch latest(UUID accountId, OffsetDateTime storedUntil) {
        List<DetectionWithAlert> newestFirst = detectionService.latestStored(accountId, storedUntil, PAGE_SIZE);
        if (newestFirst.isEmpty()) {
            return new Batch(List.of(), false, LiveFeedCursor.startingAt(storedUntil));
        }
        return new Batch(newestFirst.reversed(), false, LiveFeedCursor.after(newestFirst.getFirst().detection()));
    }

    /** One row more than a page tells whether more are waiting, without a separate count. */
    private Batch after(UUID accountId, LiveFeedCursor cursor, OffsetDateTime storedUntil) {
        List<DetectionWithAlert> found = detectionService.storedAfter(accountId, cursor.storedAt(),
                cursor.detectionId(), storedUntil, PAGE_SIZE + 1);
        boolean hasMore = found.size() > PAGE_SIZE;
        List<DetectionWithAlert> page = hasMore ? found.subList(0, PAGE_SIZE) : found;
        LiveFeedCursor next = page.isEmpty() ? cursor : LiveFeedCursor.after(page.getLast().detection());
        return new Batch(page, hasMore, next);
    }

    /** The device currently paired with the account; none when it is unpaired or has sent no position yet. */
    private List<DeviceLive> devices(UUID accountId, OffsetDateTime since) {
        return pairingService.findPairedDeviceId(accountId)
                .flatMap(deviceId -> liveState(accountId, deviceId, since))
                .stream()
                .toList();
    }

    /** The last point of the route is the latest position; only a device silent for the whole window needs a lookup. */
    private Optional<DeviceLive> liveState(UUID accountId, UUID deviceId, OffsetDateTime since) {
        List<DeviceLocation> track = locationService.track(accountId, deviceId, since);
        Optional<DeviceLocation> last = track.isEmpty()
                ? locationService.latest(accountId, deviceId)
                : Optional.of(track.getLast());
        return last.map(location -> new DeviceLive(deviceId, location, track));
    }

    private record Batch(List<DetectionWithAlert> detections, boolean hasMore, LiveFeedCursor next) {
    }
}
