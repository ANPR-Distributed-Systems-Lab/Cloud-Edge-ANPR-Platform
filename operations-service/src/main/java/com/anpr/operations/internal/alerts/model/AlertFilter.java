package com.anpr.operations.internal.alerts.model;

import java.time.OffsetDateTime;

public record AlertFilter(
        String plate,
        OffsetDateTime from,
        OffsetDateTime to
) { }
