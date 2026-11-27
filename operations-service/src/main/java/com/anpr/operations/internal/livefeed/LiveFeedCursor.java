package com.anpr.operations.internal.livefeed;

import com.anpr.operations.internal.detections.model.Detection;
import com.anpr.operations.shared.error.BadRequestException;
import com.anpr.operations.shared.error.ErrorCodes;

import java.nio.charset.StandardCharsets;
import java.time.DateTimeException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.temporal.ChronoUnit;
import java.util.Base64;
import java.util.UUID;

/**
 * Position of the live feed: the storing time and id of the last detection the client has. The id breaks ties,
 * because all detections of one batch share the storing time. Opaque to the client: Base64 of "micros:id".
 * Not a secret and not signed; a forged cursor only moves the client within its own account.
 */
public record LiveFeedCursor(OffsetDateTime storedAt, UUID detectionId) {
    private static final UUID BEFORE_ANY_ID = new UUID(0, 0);

    public static LiveFeedCursor after(Detection detection) {
        return new LiveFeedCursor(detection.getIngestedAt(), detection.getDetectionId());
    }

    /** For an account with no detections yet: every detection stored after this moment comes next. */
    public static LiveFeedCursor startingAt(OffsetDateTime storedAt) {
        return new LiveFeedCursor(storedAt, BEFORE_ANY_ID);
    }

    /** Microseconds, the precision of PostgreSQL timestamps, so the time read back matches the stored one exactly. */
    public String encode() {
        long micros = ChronoUnit.MICROS.between(Instant.EPOCH, storedAt.toInstant());
        String raw = micros + ":" + detectionId;
        return Base64.getUrlEncoder().withoutPadding().encodeToString(raw.getBytes(StandardCharsets.UTF_8));
    }

    public static LiveFeedCursor decode(String cursor) {
        try {
            String raw = new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8);
            int separator = raw.indexOf(':');
            if (separator < 0) {
                throw new IllegalArgumentException("No separator");
            }
            long micros = Long.parseLong(raw.substring(0, separator));
            OffsetDateTime storedAt = Instant.EPOCH.plus(micros, ChronoUnit.MICROS).atOffset(ZoneOffset.UTC);
            return new LiveFeedCursor(storedAt, UUID.fromString(raw.substring(separator + 1)));
        } catch (IllegalArgumentException | ArithmeticException | DateTimeException e) {
            throw new BadRequestException(ErrorCodes.INVALID_REQUEST, "Invalid cursor");
        }
    }
}
