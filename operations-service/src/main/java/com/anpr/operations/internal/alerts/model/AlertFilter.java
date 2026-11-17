package com.anpr.operations.internal.alerts.model;

import com.anpr.operations.shared.time.TimeRange;

public record AlertFilter(String plate, TimeRange period) {
}
