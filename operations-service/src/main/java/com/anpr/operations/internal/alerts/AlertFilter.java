package com.anpr.operations.internal.alerts;

import java.time.OffsetDateTime;

public record AlertFilter(
        String plate,
        OffsetDateTime from,
        OffsetDateTime to
) { }
