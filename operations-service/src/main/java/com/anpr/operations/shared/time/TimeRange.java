package com.anpr.operations.shared.time;

import com.anpr.operations.shared.error.BadRequestException;
import com.anpr.operations.shared.error.ErrorCodes;

import java.time.OffsetDateTime;

/**
 * Time range of a query: both ends optional, 'from' inclusive, 'to' exclusive. In shared because detections, alerts
 * and the radial analysis (View 2) filter by it, and the rule that 'to' is after 'from' must exist only once.
 */
public record TimeRange(OffsetDateTime from, OffsetDateTime to) {
    public TimeRange {
        if (from != null && to != null && !from.isBefore(to)) {
            throw new BadRequestException(ErrorCodes.INVALID_TIME_RANGE, "'to' must be after 'from'");
        }
    }
}
