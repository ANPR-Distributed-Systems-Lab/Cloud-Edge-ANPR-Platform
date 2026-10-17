package com.anpr.operations.shared.error;

import lombok.AccessLevel;
import lombok.NoArgsConstructor;

@NoArgsConstructor(access = AccessLevel.PRIVATE)
public final class ErrorCodes {
    public static final String VALIDATION_FAILED = "VALIDATION_FAILED";
    public static final  String ALERT_ALREADY_EXISTS = "ALERT_ALREADY_EXISTS";
    public static final String CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION";
    public static final String INTERNAL_ERROR = "INTERNAL_ERROR";
}

